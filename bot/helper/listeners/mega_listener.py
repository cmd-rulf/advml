import os
from threading import Event, Lock
import time
import random

from mega import (
    MegaApi,
    MegaError,
    MegaListener,
    MegaRequest,
    MegaTransfer
)

from bot import LOGGER, config_dict
from ..ext_utils.bot_utils import async_to_sync, sync_to_async
from bot.helper.telegram_helper.message_utils import deleteMessage

# Global lock for thread safety
mega_lock = Lock()

class AsyncExecutor:
    def __init__(self):
        self.continue_event = Event()

    def do(self, function, args):
        self.continue_event.clear()
        function(*args)
        self.continue_event.wait()

async def mega_login(executor, api, MAIL, PASS, max_retries=3, retry_delay=5):
    """Logs in to Mega with retry logic."""
    for attempt in range(max_retries):
        try:
            LOGGER.info("Attempting to log in to Mega...")
            await sync_to_async(
                executor.do,
                api.login,
                (MAIL, PASS)
            )
            LOGGER.info("Successfully logged in to Mega.")
            await perform_account_activation_tasks(api, executor)
            return True
        except Exception as e:
            LOGGER.error(f"Login failed (Attempt {attempt + 1}/{max_retries}): {e}")
            if attempt < max_retries - 1:
                time.sleep(retry_delay)
                retry_delay *= 2
            else:
                LOGGER.error("Max login retries reached.")
                return False

async def mega_logout(executor, api, folder_api=None):
    """Logs out from Mega."""
    LOGGER.info("Logging out from Mega...")
    await sync_to_async(executor.do, api.logout, ())
    if folder_api:
        await sync_to_async(executor.do, folder_api.logout, ())
    LOGGER.info("Successfully logged out from Mega.")

async def perform_account_activation_tasks(api, executor):
    """Performs Mega account activities to potentially activate the account."""
    try:
        LOGGER.info("Performing account activation tasks...")
        await sync_to_async(executor.do, api.fetchNodes, ())
        root_node = api.getRootNode()
        if root_node:
            LOGGER.info(f"Fetched root node: {root_node.getName()}")
        else:
            LOGGER.warning("Failed to fetch root node.")
            return
        account_info = await sync_to_async(executor.do, api.getAccountDetails, ())
        if account_info:
            LOGGER.info(f"Account info: {account_info}")
        else:
            LOGGER.warning("Failed to fetch account info")
        children = await sync_to_async(executor.do, api.getChildren, (root_node,))
        if children:
            LOGGER.info(f"Found {len(children)} children in root node")
        else:
            LOGGER.warning("No children found in root node")
        LOGGER.info("Account activation tasks completed.")
    except Exception as e:
        LOGGER.error(f"Error performing account activation tasks: {e}")

class MegaAppListener(MegaListener):
    _NO_EVENT_ON = (
        MegaRequest.TYPE_LOGIN,
        MegaRequest.TYPE_FETCH_NODES
    )

    def __init__(self, continue_event: Event, listener, mega_api, executor, email, password):
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
        self.executor = executor
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
            with mega_lock:
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
                if (
                    request_type not in self._NO_EVENT_ON
                    or (
                        self.node
                        and "cloud drive" not in self._name.lower()
                    )
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
                    self.listener.on_download_error,
                    f"RequestTempError: {error_message}"
                )
            self.error = error.toString()
            self.continue_event.set()

    def onTransferUpdate(self, api: MegaApi, transfer: MegaTransfer):
        if self.is_cancelled:
            api.cancelTransfer(transfer, None)
            self.continue_event.set()
            return
        self._speed = transfer.getSpeed()
        self._bytes_transferred = transfer.getTransferredBytes()

    def onTransferFinish(self, api: MegaApi, transfer, error):
        try:
            if self.is_cancelled:
                self.continue_event.set()
            elif (
                transfer.isFinished()
                and (
                    transfer.isFolderTransfer() or
                    transfer.getFileName() == self._name
                )
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
                LOGGER.info("Attempting to re-login before retrying transfer...")
                login_success = await mega_login(self.executor, self.mega_api, self.email, self.password)
                if not login_success:
                    LOGGER.error("Re-login failed. Aborting retry.")
                    break
                self.is_cancelled = False
                time.sleep(random.uniform(5, 15))
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

async def add_mega_download(self, path):
    """
    Downloads a file or folder from a Mega.nz link using the Mega SDK.

    Args:
        self: The Mirror object with attributes like link, editable, listener, etc.
        path (str): The destination directory for the downloaded file or folder.
    """
    try:
        # Initialize MegaApi and AsyncExecutor
        mega_api = MegaApi(None, None, None, 'bot')
        executor = AsyncExecutor()

        # Fetch Mega credentials
        EMAIL = config_dict.get('MEGA_EMAIL') or os.getenv('MEGA_EMAIL')
        PASSWORD = config_dict.get('MEGA_PASSWORD') or os.getenv('MEGA_PASSWORD')
        if not EMAIL or not PASSWORD:
            error_msg = "Mega credentials not provided."
            LOGGER.error(error_msg)
            await self.listener.onDownloadError(error_msg)
            return

        # Login to Mega
        login_success = await mega_login(executor, mega_api, EMAIL, PASSWORD)
        if not login_success:
            error_msg = "Failed to log in to Mega."
            LOGGER.error(error_msg)
            await self.listener.onDownloadError(error_msg)
            return

        # Initialize MegaAppListener
        continue_event = Event()
        listener = MegaAppListener(continue_event, self.listener, mega_api, executor, EMAIL, PASSWORD)

        # Start the download
        LOGGER.info(f"Starting Mega download for {self.link}")
        os.makedirs(path, exist_ok=True)

        # Download the file or folder
        await sync_to_async(
            executor.do,
            mega_api.download_url,
            (self.link, path, listener)
        )

        # Wait for completion or failure
        await sync_to_async(continue_event.wait)

        # Handle results
        if listener.error:
            LOGGER.error(f"Download failed: {listener.error}")
            await self.listener.onDownloadError(str(listener.error))
        elif listener.is_cancelled:
            LOGGER.info("Download was cancelled.")
            await self.listener.onDownloadError("Download was cancelled.")
        else:
            LOGGER.info(f"Download completed: {listener._name}")
            await self.listener.onDownloadComplete()

    except Exception as e:
        LOGGER.error(f"Error in add_mega_download: {e}")
        await self.listener.onDownloadError(str(e))
    finally:
        # Logout from Mega
        try:
            await mega_logout(executor, mega_api)
        except Exception as logout_err:
            LOGGER.error(f"Failed to logout: {logout_err}")
        # Delete the editable message
        try:
            await deleteMessage(self.editable)
        except Exception as del_err:
            LOGGER.error(f"Failed to delete message: {del_err}")
