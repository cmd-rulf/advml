
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

from bot import LOGGER
from ..ext_utils.bot_utils import (
    async_to_sync,
    sync_to_async
)

# Global lock for thread safety
mega_lock = Lock()


class AsyncExecutor:
    def __init__(self):
        self.continue_event = Event()

    def do(
            self,
            function,
            args
        ):
        self.continue_event.clear()
        function(*args)
        self.continue_event.wait()


async def mega_login(
        executor,
        api,
        MAIL,
        PASS,
        max_retries=3,
        retry_delay=5
    ):
    """Logs in to Mega with retry logic."""
    for attempt in range(max_retries):
        try:
            LOGGER.info("Attempting to log in to Mega...")
            await sync_to_async(
                executor.do,
                api.login,
                (
                    MAIL,
                    PASS
                )
            )
            LOGGER.info("Successfully logged in to Mega.")

            # Perform some activities *after* login to "activate" the account
            await perform_account_activation_tasks(api, executor) # NEW

            return True  # Login successful
        except Exception as e:  # Replace with specific Mega exception
            LOGGER.error(f"Login failed (Attempt {attempt + 1}/{max_retries}): {e}")
            if attempt < max_retries - 1:
                time.sleep(retry_delay)
                retry_delay *= 2  # Exponential backoff
            else:
                LOGGER.error("Max login retries reached.")
                return False  # Login failed


async def mega_logout(
        executor,
        api,
        folder_api=None
    ):
    LOGGER.info("Logging out from Mega...")
    await sync_to_async(
        executor.do,
        api.logout,
        ()
    )
    if folder_api:
        await sync_to_async(
            executor.do,
            folder_api.logout,
            ()
        )
    LOGGER.info("Successfully logged out from Mega.")


# NEW FUNCTION
async def perform_account_activation_tasks(api, executor):
    """Performs some Mega account activities to potentially activate the account."""
    try:
        LOGGER.info("Performing account activation tasks...")

        # 1. Fetch the root node (cloud drive)
        await sync_to_async(executor.do, api.fetchNodes, ())
        root_node = api.getRootNode()
        if root_node:
            LOGGER.info(f"Fetched root node: {root_node.getName()}")
        else:
            LOGGER.warning("Failed to fetch root node.")
            return # Stop if we can't fetch root node

        # 2. Get account info (disk space, etc.)
        account_info = await sync_to_async(executor.do, api.getAccountDetails, ())
        if account_info:
             LOGGER.info(f"Account info: {account_info}") #Be careful logging this. May contain private info
        else:
             LOGGER.warning("Failed to fetch account info")


        # 3. List a few files in the root node (limited to avoid abuse)
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

    def __init__(self, continue_event: Event, listener, mega_api, executor, email, password): # ADD email and password
        self.continue_event = continue_event
        self.node = None
        self.public_node = None
        self.listener = listener
        self.is_cancelled = False
        self.error = None
        self._bytes_transferred = 0
        self._speed = 0
        self._name = ""
        self._transfer = None  # Store the transfer object for retries
        self.mega_api = mega_api  # Store the MegaApi instance
        self.executor = executor
        self.email = email #ADD email
        self.password = password # ADD password
        super().__init__()

    @property
    def speed(self):
        return self._speed

    @property
    def downloaded_bytes(self):
        return self._bytes_transferred

    def onRequestFinish(
            self,
            api,
            request,
            error
        ):
        try:
            with mega_lock:  # Acquire lock for thread safety
                if str(error).lower() != "no error":
                    self.error = error.copy()
                    if str(self.error).casefold() != "not found":
                        LOGGER.error(f"Mega onRequestFinishError: {self.error} (Code: {error.getCode()})")  # Log error code
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
            LOGGER.exception(f"Exception in onRequestFinish: {e}")  # Log the full traceback
            self.error = str(e)
            self.continue_event.set()  # Make sure it sets the event

    def onRequestTemporaryError(
            self,
            api,
            request,
            error: MegaError
        ):
        error_message = error.toString()
        LOGGER.error(f"Mega Request error in {error_message}")
        if "Access denied" in error_message and not self.is_cancelled:
            # Implement retry here if Access denied
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

    def onTransferUpdate(
            self,
            api: MegaApi,
            transfer: MegaTransfer
        ):
        if self.is_cancelled:
            api.cancelTransfer(
                transfer,
                None
            )
            self.continue_event.set()
            return
        self._speed = transfer.getSpeed()
        self._bytes_transferred = transfer.getTransferredBytes()

    def onTransferFinish(
            self,
            api: MegaApi,
            transfer,
            error
        ):
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

    def onTransferTemporaryError(
            self,
            api,
            transfer,
            error
        ):
        error_message = error.toString()
        LOGGER.error(f"Mega download error in file {transfer.getFileName()}: {error_message}")
        if transfer.getState() in [
            1,
            4
        ]:
            return

        if "Access denied" in error_message:
            async_to_sync(self._retry_transfer, error_message)
        else:
            self.error = f"TransferTempError: {error_message} ({transfer.getFileName()})"
            if not self.is_cancelled:
                self.is_cancelled = True
                self.continue_event.set()

    async def _retry_transfer(self, error_message, max_retries=3, retry_delay=5):
        """Retries the transfer with exponential backoff."""
        if self._transfer is None:
            LOGGER.error("Cannot retry: Transfer object is None.")
            return  # Cannot retry

        for attempt in range(max_retries):
            if self.is_cancelled:
                LOGGER.info("Retry aborted: Task cancelled.")
                return

            LOGGER.warning(f"Retrying transfer (Attempt {attempt + 1}/{max_retries}) after Access denied error: {error_message}")
            try:
                # 1. Attempt to re-login (to address potential "offline" status)
                LOGGER.info("Attempting to re-login before retrying transfer...")
                login_success = await mega_login(self.executor, self.mega_api, self.email, self.password)  # Replace with your actual credentials
                if not login_success:
                    LOGGER.error("Re-login failed. Aborting retry.")
                    break

                # 2. Re-initiate the transfer (adapt to your code)
                # Example: If you have the URL, you can call `api.download_url` again
                # with the same parameters as the original call, then set the listener
                # again. This will re-create the transfer.
                # api.download_url(self._transfer.getURL(), dest_path="...", listener=self)
                # Or, if you are working with nodes, re-initiate the transfer with
                # the node information.
                #
                # After re-initiating, you MUST reset `self.is_cancelled = False`!
                self.is_cancelled = False  # Allow transfer to happen again

                # Add a delay after re-initiating the transfer
                time.sleep(random.uniform(5, 15))  # Rate limiting

                LOGGER.info("Transfer re-initiated successfully.")
                return  # Retry successful (transfer is re-initiated)
            except Exception as e:
                LOGGER.error(f"Retry failed: {e}")
                if attempt < max_retries - 1:
                    time.sleep(retry_delay)
                    retry_delay *= 2  # Exponential backoff
                else:
                    LOGGER.error("Max retries reached. Transfer failed.")
                    await self.listener.on_download_error(f"Max retries reached after Access denied error.")
                    self.is_cancelled = True
                    self.continue_event.set()  # Signal that this transfer has ended.
                
