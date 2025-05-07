from asyncio import Event
import time
import random

from mega import MegaApi, MegaError, MegaListener, MegaRequest, MegaTransfer

from ... import LOGGER
from ..ext_utils.bot_utils import async_to_sync, sync_to_async


class AsyncMega:
    def __init__(self):
        self.api = None
        self.folder_api = None
        self.continue_event = Event()

    async def run(self, function, *args, **kwargs):
        self.continue_event.clear()
        await sync_to_async(function, *args, **kwargs)
        await self.continue_event.wait()

    async def login(self, email, password, max_retries=3, retry_delay=5):
        """Logs in to Mega with retry logic."""
        for attempt in range(max_retries):
            try:
                LOGGER.info("Attempting to log in to Mega...")
                await self.run(self.api.login, email, password)
                LOGGER.info("Successfully logged in to Mega.")

                # Perform account activation tasks
                await self.perform_account_activation_tasks()
                return True
            except Exception as e:
                LOGGER.error(f"Login failed (Attempt {attempt + 1}/{max_retries}): {e}")
                if attempt < max_retries - 1:
                    time.sleep(retry_delay)
                    retry_delay *= 2  # Exponential backoff
                else:
                    LOGGER.error("Max login retries reached.")
                    return False

    async def logout(self):
        LOGGER.info("Logging out from Mega...")
        await self.run(self.api.logout)
        if self.folder_api:
            await self.run(self.folder_api.logout)
        LOGGER.info("Successfully logged out from Mega.")

    async def perform_account_activation_tasks(self):
        """Performs Mega account activities to potentially activate the account."""
        try:
            LOGGER.info("Performing account activation tasks...")

            # Fetch the root node
            await self.run(self.api.fetchNodes)
            root_node = self.api.getRootNode()
            if root_node:
                LOGGER.info(f"Fetched root node: {root_node.getName()}")
            else:
                LOGGER.warning("Failed to fetch root node.")
                return

            # Get account info
            account_info = await self.run(self.api.getAccountDetails)
            if account_info:
                LOGGER.info(f"Account info retrieved")
            else:
                LOGGER.warning("Failed to fetch account info")

            # List a few files in the root node
            children = await self.run(self.api.getChildren, root_node)
            if children:
                LOGGER.info(f"Found {len(children)} children in root node")
            else:
                LOGGER.warning("No children found in root node")

            LOGGER.info("Account activation tasks completed.")
        except Exception as e:
            LOGGER.error(f"Error performing account activation tasks: {e}")

    def __getattr__(self, name):
        attr = getattr(self.api, name)
        if callable(attr):
            async def wrapper(*args, **kwargs):
                return await self.run(attr, *args, **kwargs)
            return wrapper
        return attr


class MegaAppListener(MegaListener):
    _NO_EVENT_ON = (MegaRequest.TYPE_LOGIN, MegaRequest.TYPE_FETCH_NODES)

    def __init__(self, continue_event: Event, listener, mega_api, email=None, password=None):
        self.continue_event = continue_event
        self.node = None
        self.public_node = None
        self.listener = listener
        self.is_cancelled = False
        self.error = None
        self._bytes_transferred = 0
        self._speed = 0
        self._name = ""
        self._transfer = None
        self.mega_api = mega_api
        self.email = email
        self.password = password
        super().__init__()

    @property
    def speed(self):
        return self._speed

    @property
    def downloaded_bytes(self):
        return self._bytes_transferred

    def onRequestFinish(self, api, request, error):
        try:
            if str(error).lower() != "no error":
                self.error = error.copy()
                if str(self.error).casefold() != "not found":
                    LOGGER.error(f"Mega onRequestFinishError: {self.error} (Code: {error.getCode()})")
                self.continue_event.set()
                return

            request_type = request.getType()

            if request_type == MegaRequest.TYPE_LOGIN:
                api.fetchNodes()
            elif request_type == MegaRequest.TYPE_GET_PUBLIC_NODE:
                self.public_node = request.getPublicMegaNode()
                self._name = self.public_node.getName()
            elif request_type == MegaRequest.TYPE_FETCH_NODES:
                LOGGER.info("Fetching Root Node.")
                self.node = api.getRootNode()
                self._name = self.node.getName()
                LOGGER.info(f"Node Name: {self.node.getName()}")

            if request_type not in self._NO_EVENT_ON or (
                self.node and "cloud drive" not in self._name.lower()
            ):
                self.continue_event.set()
        except Exception as e:
            LOGGER.exception(f"Exception in onRequestFinish: {e}")
            self.error = str(e)
            self.continue_event.set()

    def onRequestTemporaryError(self, api, request, error: MegaError):
        error_message = error.toString()
        LOGGER.error(f"Mega Request error in {error_message}")
        if "Access denied" in error_message and not self.is_cancelled:
            async_to_sync(self._retry_transfer, error_message)
        else:
            if not self.is_cancelled:
                self.is_cancelled = True
                async_to_sync(
                    self.listener.on_download_error, f"RequestTempError: {error_message}"
                )
            self.error = error_message
            self.continue_event.set()

    def onTransferUpdate(self, api: MegaApi, transfer: MegaTransfer):
        if self.is_cancelled:
            api.cancelTransfer(transfer, None)
            self.continue_event.set()
            return
        self._speed = transfer.getSpeed()
        self._bytes_transferred = transfer.getTransferredBytes()
        self._transfer = transfer

    def onTransferFinish(self, api: MegaApi, transfer: MegaTransfer, error):
        try:
            if self.is_cancelled:
                self.continue_event.set()
            elif transfer.isFinished() and (
                transfer.isFolderTransfer() or transfer.getFileName() == self._name
            ):
                async_to_sync(self.listener.on_download_complete)
                self.continue_event.set()
        except Exception as e:
            LOGGER.error(e)

    def onTransferTemporaryError(self, api, transfer, error):
        error_message = error.toString()
        LOGGER.error(f"Mega download error in file {transfer.getFileName()}: {error_message}")
        if transfer.getState() in [1, 4]:
            return
        if "Access denied" in error_message:
            async_to_sync(self._retry_transfer, error_message)
        else:
            self.error = f"TransferTempError: {error_message} ({transfer.getFileName()})"
            if not self.is_cancelled:
                self.is_cancelled = True
                self.continue_event.set()

    async def cancel_task(self):
        self.is_cancelled = True
        await self.listener.on_download_error("Download Canceled by user")

    async def _retry_transfer(self, error_message, max_retries=3, retry_delay=5):
        """Retries the transfer with exponential backoff."""
        if self._transfer is None:
            LOGGER.error("Cannot retry: Transfer object is None.")
            return

        for attempt in range(max_retries):
            if self.is_cancelled:
                LOGGER.info("Retry aborted: Task cancelled.")
                return

            LOGGER.warning(f"Retrying transfer (Attempt {attempt + 1}/{max_retries}) after Access denied error: {error_message}")
            try:
                # Re-login to address potential "offline" status
                LOGGER.info("Attempting to re-login before retrying transfer...")
                async_mega = AsyncMega()
                async_mega.api = self.mega_api
                login_success = await async_mega.login(self.email, self.password)
                if not login_success:
                    LOGGER.error("Re-login failed. Aborting retry.")
                    break

                # Re-initiate the transfer
                self.is_cancelled = False
                if self.public_node:
                    await self.run(self.mega_api.startDownload, self.public_node)
                elif self.node:
                    await self.run(self.mega_api.startDownload, self.node)
                time.sleep(random.uniform(5, 15))  # Rate limiting
                LOGGER.info("Transfer re-initiated successfully.")
                return
            except Exception as e:
                LOGGER.error(f"Retry failed: {e}")
                if attempt < max_retries - 1:
                    time.sleep(retry_delay)
                    retry_delay *= 2
                else:
                    LOGGER.error("Max retries reached. Transfer failed.")
                    await self.listener.on_download_error(f"Max retries reached after Access denied error.")
                    self.is_cancelled = True
                    self.continue_event.set()