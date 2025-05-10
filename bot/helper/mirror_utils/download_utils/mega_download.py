from asyncio import Event
from mega import MegaApi, MegaListener, MegaRequest, MegaTransfer, MegaError
from bot import (
    LOGGER,
    config_dict,
    task_dict_lock,
    task_dict,
    non_queued_dl,
    non_queued_up,
    queue_dict_lock,
    MirrorStatus,
)
from bot.helper.ext_utils.links_utils import get_mega_link_type
from bot.helper.telegram_helper.message_utils import sendMessage, sendStatusMessage
from bot.helper.ext_utils.bot_utils import (
    async_to_sync,
    sync_to_async,
)
from bot.helper.mirror_utils.status_utils.mega_download_status import MegaDownloadStatus
from bot.helper.mirror_utils.status_utils.queue_status import QueueStatus
from bot.helper.ext_utils.task_manager import (
    check_running_tasks,
    check_limits_size,
    stop_duplicate_check,
    start_up_from_queued,
)
from aiofiles.os import makedirs
from secrets import token_hex
from os import path as ospath

class MegaAppListener(MegaListener):
    _NO_EVENT_ON = (MegaRequest.TYPE_LOGIN, MegaRequest.TYPE_FETCH_NODES)
    NO_ERROR = "no error"

    def __init__(self, continue_event: Event, listener):
        self.continue_event = continue_event
        self.node = None
        self.public_node = None
        self.listener = listener
        self.is_cancelled = False
        self.error = None
        self.__bytes_transferred = 0
        self.__speed = 0
        self.__name = ""
        super().__init__()

    @property
    def speed(self):
        return self.__speed

    @property
    def downloaded_bytes(self):
        return self.__bytes_transferred

    def onRequestFinish(self, api, request, error):
        if str(error).lower() != "no error":
            self.error = error.copy()
            LOGGER.error(f"Mega onRequestFinishError: {self.error}")
            self.continue_event.set()
            return
        request_type = request.getType()
        if request_type == MegaRequest.TYPE_LOGIN:
            api.fetchNodes()
        elif request_type == MegaRequest.TYPE_GET_PUBLIC_NODE:
            self.public_node = request.getPublicMegaNode()
            self.__name = self.public_node.getName()
        elif request_type == MegaRequest.TYPE_FETCH_NODES:
            LOGGER.info("Fetching Root Node.")
            self.node = api.getRootNode()
            self.__name = self.node.getName()
            LOGGER.info(f"Node Name: {self.node.getName()}")
        if (
            request_type not in self._NO_EVENT_ON
            or self.node
            and "cloud drive" not in self.__name.lower()
        ):
            self.continue_event.set()

    def onRequestTemporaryError(self, api, request, error: MegaError):
        LOGGER.error(f"Mega Request error in {error}")
        if not self.is_cancelled:
            self.is_cancelled = True
            async_to_sync(
                self.listener.onDownloadError, f"RequestTempError: {error.toString()}"
            )
        self.error = error.toString()
        self.continue_event.set()

    def onTransferUpdate(self, api: MegaApi, transfer: MegaTransfer):
        if self.is_cancelled:
            api.cancelTransfer(transfer, None)
            self.continue_event.set()
            return
        self.__speed = transfer.getSpeed()
        self.__bytes_transferred = transfer.getTransferredBytes()

    def onTransferFinish(self, api: MegaApi, transfer: MegaTransfer, error):
        try:
            if self.is_cancelled:
                self.continue_event.set()
            elif transfer.isFinished() and (
                transfer.isFolderTransfer() or transfer.getFileName() == self.__name
            ):
                async_to_sync(self.listener.onDownloadComplete)
                self.continue_event.set()
        except Exception as e:
            LOGGER.error(e)
            self.error = str(e)
            self.continue_event.set()

    def onTransferTemporaryError(self, api, transfer, error):
        filen = transfer.getFileName()
        state = transfer.getState()
        errStr = error.toString()
        LOGGER.error(f"Mega download error in file {transfer} {filen}: {error}")
        if state in [1, 4]:
            return
        self.error = errStr
        if not self.is_cancelled:
            self.is_cancelled = True
            async_to_sync(
                self.listener.onDownloadError, f"TransferTempError: {errStr} ({filen})"
            )
            self.continue_event.set()

    async def cancel_task(self):
        self.is_cancelled = True
        await self.listener.onDownloadError("Download Canceled by user")

class AsyncExecutor:
    def __init__(self):
        self.continue_event = Event()

    async def do(self, function, args):
        self.continue_event.clear()
        await sync_to_async(function, *args)
        await self.continue_event.wait()

async def add_mega_download(mega_link, path, listener, name):
    MEGA_EMAIL = config_dict["MEGA_EMAIL"]
    MEGA_PASSWORD = config_dict["MEGA_PASSWORD"]

    executor = AsyncExecutor()
    api = MegaApi(None, None, None, "SEARCH-X")
    folder_api = None

    mega_listener = MegaAppListener(executor.continue_event, listener)
    api.addListener(mega_listener)

    if MEGA_EMAIL and MEGA_PASSWORD:
        await executor.do(api.login, (MEGA_EMAIL, MEGA_PASSWORD))
    else:
        LOGGER.error("Mega credentials not provided.")
        await listener.onDownloadError("Mega credentials not provided.")
        return

    try:
        if get_mega_link_type(mega_link) == "file":
            await executor.do(api.getPublicNode, (mega_link,))
            node = mega_listener.public_node
        else:
            folder_api = MegaApi(None, None, None, "SEARCH-X")
            folder_api.addListener(mega_listener)
            await executor.do(folder_api.loginToFolder, (mega_link,))
            node = await sync_to_async(folder_api.authorizeNode, mega_listener.node)

        if mega_listener.error is not None:
            await sendMessage(listener.message, str(mega_listener.error))
            return

        name = name or mega_listener.node.getName() or mega_listener.public_node.getName()
        LOGGER.info(f"Mega Download: {name}")

        # Check for duplicate files
        file, new_name = await stop_duplicate_check(listener)
        if file:
            msg = f"File/Folder is already available in Drive.\nHere are the search results:\n{file}"
            buttons = None  # ButtonMaker logic can be added if needed
            await sendMessage(listener.message, msg, buttons)
            return
        if new_name:
            name = new_name

        # Check size limits
        size = api.getSize(node)
        if limit_exceeded := await check_limits_size(listener, size):
            await sendMessage(listener.message, limit_exceeded)
            return

        # Check running tasks and queue if necessary
        added_to_queue, event = await check_running_tasks(listener.mid, state='dl')
        gid = token_hex(5)

        if added_to_queue:
            LOGGER.info(f"Added to Queue/Download: {name}")
            async with task_dict_lock:
                task_dict[listener.mid] = QueueStatus(listener, size, gid, 'dl')
            await listener.onDownloadStart()
            await sendStatusMessage(listener.message)
            await event.wait()
            async with task_dict_lock:
                if listener.mid not in task_dict:
                    return
            LOGGER.info(f"Start Queued Download from Mega: {name}")
            from_queue = True
        else:
            from_queue = False

        # Add task to task dictionary
        async with task_dict_lock:
            task_dict[listener.mid] = MegaDownloadStatus(
                name, size, gid, mega_listener, listener, path
            )
        async with queue_dict_lock:
            non_queued_dl.add(listener.mid)

        if not from_queue:
            await listener.onDownloadStart()
            await sendStatusMessage(listener.message)
            LOGGER.info(f"Download from Mega: {name}")

        # Start the download
        await makedirs(path, exist_ok=True)
        await executor.do(api.startDownload, (node, path, name, None, False, None))

        # Wait for completion
        await executor.continue_event.wait()

        # Handle results
        if mega_listener.error:
            await listener.onDownloadError(str(mega_listener.error))
        elif mega_listener.is_cancelled:
            await listener.onDownloadError("Download Canceled by user")
        else:
            # Update task status to uploading
            async with task_dict_lock:
                if listener.mid in task_dict:
                    task_dict[listener.mid].set_upload_phase()
                    async with queue_dict_lock:
                        non_queued_dl.discard(listener.mid)
                        non_queued_up.add(listener.mid)
            await listener.onDownloadComplete()
            LOGGER.info(f"Mega download completed, initiating upload for {name}")
            await start_up_from_queued(listener.mid)  # Trigger upload queue processing

    except Exception as e:
        LOGGER.error(f"Error in add_mega_download: {e}")
        await listener.onDownloadError(str(e))
    finally:
        # Cleanup
        try:
            await executor.do(api.logout, ())
            if folder_api is not None:
                await executor.do(folder_api.logout, ())
        except Exception as e:
            LOGGER.error(f"Failed to logout: {e}")
        # Remove from download queue
        async with queue_dict_lock:
            non_queued_dl.discard(listener.mid)