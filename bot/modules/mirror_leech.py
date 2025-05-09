from aiofiles.os import path as aiopath
from asyncio import sleep, gather
from base64 import b64encode
from os import path as ospath
from pyrogram import Client
from pyrogram.filters import command
from pyrogram.handlers import MessageHandler
from pyrogram.types import Message
from re import match as re_match
from urllib.parse import urlparse

from bot import bot, config_dict, LOGGER
from bot.helper.ext_utils.bot_utils import get_content_type, is_premium_user, sync_to_async, new_task, arg_parser
from bot.helper.ext_utils.commons_check import UseCheck
from bot.helper.ext_utils.conf_loads import intialize_savebot
from bot.helper.ext_utils.exceptions import DirectDownloadLinkException
from bot.helper.ext_utils.links_utils import get_link, is_url, is_magnet, is_mega_link, is_media, is_gdrive_link, is_sharer_link, is_gdrive_id, is_tele_link, is_rclone_path
from bot.helper.listeners.tasks_listener import TaskListener
from bot.helper.mirror_utils.download_utils.aria2_download import add_aria2c_download
from bot.helper.mirror_utils.download_utils.direct_downloader import add_direct_download
from bot.helper.mirror_utils.download_utils.direct_link_generator import direct_link_generator
from bot.helper.mirror_utils.download_utils.gd_download import add_gd_download
from bot.helper.mirror_utils.download_utils.jd_download import add_jd_download
from bot.helper.mirror_utils.download_utils.qbit_download import add_qb_torrent
from bot.helper.mirror_utils.download_utils.rclone_download import add_rclone_download
from bot.helper.mirror_utils.download_utils.telegram_download import TelegramDownloadHelper
from bot.helper.mirror_utils.download_utils.mega_download import add_mega_download
from bot.helper.telegram_helper.bot_commands import BotCommands
from bot.helper.telegram_helper.filters import CustomFilters
from bot.helper.telegram_helper.message_utils import sendMessage, deleteMessage, auto_delete_message, editMessage, get_tg_link_message
from bot.helper.video_utils.selector import SelectMode
from myjd.exception import MYJDException


class Mirror(TaskListener):
    def __init__(self, client: Client, message: Message, isQbit=False, isJd=False, isLeech=False, vidMode=None, sameDir=None, bulk=None, multiTag=None, options=''):
        if sameDir is None:
            sameDir = {}
        if bulk is None:
            bulk = []
        self.message = message
        self.client = client
        self.multiTag = multiTag
        self.options = options
        self.sameDir = sameDir
andoli

System: You are Grok 3 built by xAI.

I've received your request to incorporate the old versions of `mega_download_status.py` and `queue_status.py` into the Mega download system for the bot application. Below, I’ll provide a complete solution that integrates these files with the previously provided `mega_download.py` and `mirror.py`, along with all necessary additional files to ensure the system works. The solution will include updates to handle the dependencies and references in the old status files, ensuring compatibility with the bot’s architecture.

### Approach
1. **Incorporate Old Status Files**:
   - Use the provided `mega_download_status.py` and `queue_status.py` as the primary status management classes.
   - Update `mega_download.py` to align with these status classes, ensuring proper initialization and method calls.
2. **Update Dependencies**:
   - Provide implementations for `MirrorStatus`, `get_readable_file_size`, `get_readable_time`, and other utilities referenced in the status files.
   - Include necessary modules like `task_manager.py` for queue and limit checks, and `status_utils.py` for status constants.
3. **Complete File Set**:
   - Provide all required files, including updated versions of previously provided files (`bot.py`, `bot_utils.py`, etc.) to resolve dependencies.
   - Ensure the `mirror.py` integration for Mega downloads remains consistent with the provided code.
4. **Project Structure and Setup**:
   - Outline the project structure and provide installation instructions to set up the environment.

### Complete Code Solution
Below is the full set of files required to make the Mega download system work with the old `mega_download_status.py` and `queue_status.py`. Each file is wrapped in an `<xaiArtifact>` tag with a unique `artifact_id` and appropriate `contentType`. If a file is unchanged from the previous response, I’ll reuse its `artifact_id` to indicate it’s an updated version.

#### 1. `mega_download.py`
This is the corrected version, updated to work with the old `mega_download_status.py` and `queue_status.py`.

<xaiArtifact artifact_id="31db247c-46d9-49cf-b9b4-39ba80781776" artifact_version_id="884c121c-65a2-4343-8e3d-c982c30ceb9a" title="mega_download.py" contentType="text/python">
from asyncio import Event
from mega import MegaApi, MegaListener, MegaRequest, MegaTransfer, MegaError
from bot import (
    LOGGER,
    config_dict,
    download_dict_lock,
    download_dict,
    non_queued_dl,
    queue_dict_lock,
)
from bot.helper.telegram_helper.message_utils import sendMessage, sendStatusMessage
from bot.helper.ext_utils.bot_utils import (
    get_mega_link_type,
    async_to_sync,
    sync_to_async,
)
from bot.helper.mirror_utils.status_utils.mega_download_status import MegaDownloadStatus
from bot.helper.mirror_utils.status_utils.queue_status import QueueStatus
from bot.helper.ext_utils.task_manager import (
    is_queued,
    limit_checker,
    stop_duplicate_check,
)
from aiofiles.os import makedirs
from secrets import token_hex


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

    async def cancel_download(self):
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
        await executor.do(api.logout, ())
        if folder_api is not None:
            await executor.do(folder_api.logout, ())
        return

    name = name or node.getName()
    msg, button = await stop_duplicate_check(name, listener)
    if msg:
        await sendMessage(listener.message, msg, button)
        await executor.do(api.logout, ())
        if folder_api is not None:
            await executor.do(folder_api.logout, ())
        return

    gid = token_hex(5)
    size = api.getSize(node)
    if limit_exceeded := await limit_checker(size, listener, isMega=True):
        await sendMessage(listener.message, limit_exceeded)
        return
    added_to_queue, event = await is_queued(listener.uid)
    if added_to_queue:
        LOGGER.info(f"Added to Queue/Download: {name}")
        async with download_dict_lock:
            download_dict[listener.uid] = QueueStatus(listener, size, gid, 'dl')
        await listener.onDownloadStart()
        await sendStatusMessage(listener.message)
        await event.wait()
        async with download_dict_lock:
            if listener.uid not in download_dict:
                await executor.do(api.logout, ())
                if folder_api is not None:
                    await executor.do(folder_api.logout, ())
                return
        from_queue = True
        LOGGER.info(f"Start Queued Download from Mega: {name}")
    else:
        from_queue = False

    async with download_dict_lock:
        download_dict[listener.uid] = MegaDownloadStatus(
            name, size, gid, mega_listener, listener.message
        )
    async with queue_dict_lock:
        non_queued_dl.add(listener.uid)

    if from_queue:
        LOGGER.info(f"Start Queued Download from Mega: {name}")
    else:
        await listener.onDownloadStart()
        await sendStatusMessage(listener.message)
        LOGGER.info(f"Download from Mega: {name}")

    await makedirs(path, exist_ok=True)
    await executor.do(api.startDownload, (node, path, name, None, False, None))
    await executor.do(api.logout, ())
    if folder_api is not None:
        await executor.do(folder_api.logout, ())
