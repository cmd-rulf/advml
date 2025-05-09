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
        self.bulk = bulk
        super().__init__()
        self.isQbit = isQbit
        self.isLeech = isLeech
        self.vidMode = vidMode
        self.isJd = isJd

    @new_task
    async def newEvent(self):
        text = self.message.text.split('\n')
        await self.getTag(text)

        reply_to = self.message.reply_to_message
        if fmsg := await UseCheck(self.message, self.isLeech).run(True, daily=True, ml_chek=True, session=True, send_pm=True):
            self.removeFromSameDir()
            await auto_delete_message(self.message, fmsg, reply_to)
            return

        arg_base = {'-i': 0,
                    '-sp': 0,
                    '-b': False,
                    '-d': False,
                    '-e': False,
                    '-gf': False,
                    '-j': False,
                    '-s': False,
                    '-ss': False,
                    '-sv': False,
                    '-vt': False,
                    '-z': False,
                    '-ap': '',
                    '-au': '',
                    '-h': '',
                    '-m': '',
                    '-n': '',
                    '-rcf': '',
                    '-t': '',
                    '-up': '',
                    'link': ''}

        input_list = text[0].split(' ')
        args = arg_parser(input_list[1:], arg_base)

        self.compress = args['-z']
        self.extract = args['-e']
        self.isGofile = args['-gf']
        self.join = args['-j']
        self.link = args['link']
        self.name = args['-n'].replace('/', '')
        self.rcFlags = args['-rcf']
        self.sampleVideo = args['-sv']
        self.screenShots = args['-ss']
        self.seed = args['-d']
        self.select = args['-s']
        self.splitSize = args['-sp']
        self.thumb = args['-t']
        self.upDest = args['-up']
        self.isRename = self.name

        folder_name = args['-m'].replace('/', '')
        headers = args['-h']
        isBulk = args['-b']
        vidTool = args['-vt']
        file_ = ratio = seed_time = None
        bulk_start = bulk_end = 0

        try:
            self.multi = int(args['-i'])
        except:
            self.multi = 0

        if not isinstance(self.seed, bool):
            dargs = self.seed.split(':')
            ratio = dargs[0] or None
            if len(dargs) == 2:
                seed_time = dargs[1] or None
            self.seed = True

        if not isinstance(isBulk, bool):
            dargs = isBulk.split(':')
            bulk_start = dargs[0] or None
            if len(dargs) == 2:
                bulk_end = dargs[1] or None
            isBulk = True

        if config_dict['PREMIUM_MODE'] and not is_premium_user(self.user_id) and (self.multi > 0 or isBulk):
            await sendMessage(f'Upss {self.tag}, multi/bulk mode for premium user only', self.message)
            return

        if not isBulk:
            if folder_name:
                self.seed = False
                ratio = seed_time = None
                if not self.sameDir:
                    self.sameDir = {'total': self.multi, 'tasks': set(), 'name': folder_name}
                self.sameDir['tasks'].add(self.mid)
            elif self.sameDir:
                self.sameDir['total'] -= 1
        else:
            if vidTool and not self.vidMode and self.sameDir:
                self.vidMode = await SelectMode(self).get_buttons()
                if not self.vidMode:
                    return
            await self.initBulk(input_list, bulk_start, bulk_end, Mirror)
            return

        if self.bulk:
            del self.bulk[0]

        if vidTool and (not self.vidMode or not self.sameDir):
            self.vidMode = await SelectMode(self).get_buttons()
            if not self.vidMode:
                self.removeFromSameDir()
                return

        self.run_multi(input_list, folder_name, Mirror)

        path = ospath.join(f'{config_dict["DOWNLOAD_DIR"]}{self.mid}', folder_name)

        self.link = self.link or get_link(self.message)

        self.editable = await sendMessage('<i>Checking request, please wait...</i>', self.message)
        if self.link:
            await sleep(0.5)

        if self.link and is_tele_link(self.link):
            try:
                await intialize_savebot(self.user_dict.get('session_string'), True, self.user_id)
                self.session, reply_to = await get_tg_link_message(self.link, self.user_id)
            except Exception as e:
                LOGGER.error(e, exc_info=True)
                await editMessage(f'ERROR: {e}', self.editable)
                self.removeFromSameDir()
                return

        if isinstance(reply_to, list):
            self.bulk = reply_to
            self.sameDir = {}
            b_msg = input_list[:1]
            self.options = ' '.join(input_list[1:]).replace(self.link, '')
            b_msg.append(f'{self.bulk[0]} -i {len(self.bulk)} {self.options}')
            nextmsg = await sendMessage(' '.join(b_msg), self.message)
            nextmsg = await self.client.get_messages(self.message.chat.id, nextmsg.id)
            if self.message.from_user:
                nextmsg.from_user = self.message.from_user
            else:
                nextmsg.sender_chat = self.message.sender_chat
            Mirror(self.client, nextmsg, self.isQbit, self.isJd, self.isLeech, self.vidMode, self.sameDir, self.bulk, self.multiTag, self.options).newEvent()
            await deleteMessage(self.editable)
            return

        if reply_to:
            file_ = is_media(reply_to)
            if reply_to.document and (file_.mime_type == 'application/x-bittorrent' or file_.file_name.endswith('.torrent')):
                self.link = await reply_to.download()
                file_ = None

        if not is_url(self.link) and not is_magnet(self.link) and not await aiopath.exists(self.link) and not is_rclone_path(self.link) and not is_gdrive_id(self.link) and not file_:
            await gather(editMessage(f'Where Are Links/Files, type /{BotCommands.HelpCommand} for more details.', self.editable), auto_delete_message(self.message, self.editable))
            self.removeFromSameDir()


            return

        if self.link:
            LOGGER.info(self.link)

        if self.isGofile:
            await editMessage('<i>GoFile upload has been enabled!</i>', self.editable)
            await sleep(0.5)

        try:
            await self.beforeStart()
        except Exception as e:
            await editMessage(str(e), self.editable)
            self.removeFromSameDir()
            return

        if is_mega_link(self.link):
            self.isJd = False

        if is_magnet(self.link):
            self.isJd = False

        if (not self.isJd and not self.isQbit and not is_magnet(self.link) and not is_rclone_path(self.link) and
            not is_gdrive_link(self.link) and not self.link.endswith('.torrent') and not is_gdrive_id(self.link) and not file_):
            self.isSharer = is_sharer_link(self.link)
            content_type = (await get_content_type(self.link))[0]
            if not content_type or re_match(r'text/html|text/plain', content_type):
                host = urlparse(self.link).netloc
                await editMessage(f'<i>Generating direct link from {host}, please wait...</i>', self.editable)
                try:
                    self.link = await sync_to_async(direct_link_generator, self.link)
                    LOGGER.info('Generated link: %s', self.link)
                    if isinstance(self.link, dict):
                        contents = self.link['contents']
                        if len(contents) == 1:
                            msg = f'<i>Found direct link:</i>\n<code>{contents[0]["url"]}</code>'
                        else:
                            msg = '<i>Found folder ddl link...</i>'
                    elif isinstance(self.link, tuple):
                        if len(self.link) == 3:
                            self.link, self.name, headers = self.link
                        else:
                            self.link, headers = self.link
                        msg = f'<i>Found direct link:</i>\n<code>{self.link}</code>'
                    else:
                        msg = f"<i>Found {'drive' if 'drive.google.com' in self.link else 'direct'} link:</i>\n<code>{self.link}</code>"
                    await editMessage(msg, self.editable)
                    await sleep(1)
                except DirectDownloadLinkException as e:
                    if str(e).startswith('ERROR:'):
                        await editMessage(f'{self.tag}, {e}', self.editable)
                        self.removeFromSameDir()
                        return
        if not self.isJd:
            await deleteMessage(self.editable)

        if file_:
            await TelegramDownloadHelper(self).add_download(reply_to, path)
        elif isinstance(self.link, dict):
            await add_direct_download(self, path)
        elif self.isJd:
            try:
                await add_jd_download(self, f'{path}/')
            except (Exception, MYJDException) as e:
                LOGGER.error(e)
                await editMessage(f'{e}'.strip(), self.editable)
                self.removeFromSameDir()
                return
        elif is_rclone_path(self.link):
            await add_rclone_download(self, path)
        elif is_gdrive_link(self.link) or is_gdrive_id(self.link):
            await add_gd_download(self, path)
        
        elif self.isQbit:
            await add_qb_torrent(self, path, ratio, seed_time)
        else:
            ussr, pssw = args['-au'], args['-ap']
            if ussr or pssw:
                auth = f'{ussr}:{pssw}'
                headers += f" authorization: Basic {b64encode(auth.encode()).decode('ascii')}"
            if 'static.romsget.io' in self.link:
                headers = 'Referer: https://www.romsget.io/'
            await add_aria2c_download(self, path, headers, ratio, seed_time)


async def mirror(client: Client, message: Message):
    Mirror(client, message).newEvent()


async def qb_mirror(client: Client, message: Message):
    Mirror(client, message, isQbit=True).newEvent()


async def leech(client: Client, message: Message):
    Mirror(client, message, isLeech=True).newEvent()


async def qb_leech(client: Client, message: Message):
    Mirror(client, message, isQbit=True, isLeech=True).newEvent()


async def jd_mirror(client: Client, message: Message):
    Mirror(client, message, isJd=True).newEvent()


async def jd_leech(client: Client, message: Message):
    Mirror(client, message, isLeech=True, isJd=True).newEvent()


bot.add_handler(MessageHandler(mirror, filters=command(BotCommands.MirrorCommand) & CustomFilters.authorized))
bot.add_handler(MessageHandler(qb_mirror, filters=command(BotCommands.QbMirrorCommand) & CustomFilters.authorized))
bot.add_handler(MessageHandler(leech, filters=command(BotCommands.LeechCommand) & CustomFilters.authorized))
bot.add_handler(MessageHandler(qb_leech, filters=command(BotCommands.QbLeechCommand) & CustomFilters.authorized))
bot.add_handler(MessageHandler(jd_mirror, filters=command(BotCommands.JdMirrorCommand) & CustomFilters.authorized))
bot.add_handler(MessageHandler(jd_leech, filters=command(BotCommands.JdLeechCommand) & CustomFilters.authorized))



can you see this code and tell me why mega.nz links are downloading try with arias2 

The issue where Mega.nz links are being downloaded using aria2c instead of a more suitable method (like a Mega-specific downloader) stems from the logic in the Mirror class's newEvent method. Let's analyze the relevant parts of the code to understand why this happens and suggest a potential fix.
Analysis of the Code

    Link Type Detection:
        The code checks the type of the provided link using helper functions like is_mega_link, is_magnet, is_rclone_path, is_gdrive_link, is_gdrive_id, etc., defined in bot.helper.ext_utils.links_utils.
        Specifically, for Mega.nz links, the is_mega_link(self.link) function is called to identify if the link is a Mega.nz URL.
    Handling Mega.nz Links:
        The code contains this condition:
        python

    if is_mega_link(self.link):
        self.isJd = False
    This ensures that Mega.nz links are not processed using JDownloader (isJd), which is correct since JDownloader is one of the download methods.
    However, there is no specific handling for Mega.nz links beyond disabling isJd. The code proceeds to the next conditions, and if none of the other specific conditions (e.g., is_rclone_path, is_gdrive_link, is_magnet, etc.) match, it falls back to the default download method, which is add_aria2c_download.

Default Download Path (aria2c):

    At the end of the method, if none of the specialized download handlers are triggered, the code calls:
    python

        else:
            ussr, pssw = args['-au'], args['-ap']
            if ussr or pssw:
                auth = f'{ussr}:{pssw}'
                headers += f" authorization: Basic {b64encode(auth.encode()).decode('ascii')}"
            if 'static.romsget.io' in self.link:
                headers = 'Referer: https://www.romsget.io/'
            await add_aria2c_download(self, path, headers, ratio, seed_time)
        This block uses aria2c (via add_aria2c_download) as the fallback for any link that doesn't match a specific handler. Since Mega.nz links are not explicitly handled with a dedicated downloader (e.g., megadl or a Mega SDK), they fall into this default case and are processed by aria2c.
    Why Aria2c for Mega.nz?:
        Mega.nz links require special handling due to their encryption and API-based access. Aria2c is a general-purpose downloader that can handle HTTP/HTTPS links, but it is not optimized for Mega.nz's specific requirements (e.g., handling Mega's API, decryption keys, or rate limits).
        Without a dedicated Mega.nz downloader, the code attempts to treat the Mega.nz link as a standard HTTP link, passing it to aria2c. This may result in failed downloads or errors because aria2c cannot natively handle Mega.nz's proprietary protocol or authentication.

Why This Happens

The root cause is the lack of a dedicated handler for Mega.nz links in the newEvent method. After identifying a Mega.nz link with is_mega_link, the code only disables isJd and does not route the link to a Mega-specific download function (e.g., one that uses the Mega SDK or a tool like megadl). Instead, it continues through the condition chain and eventually reaches the default add_aria2c_download handler.
Suggested Fix

To ensure Mega.nz links are handled appropriately, you should add a dedicated handler for Mega.nz links, similar to how GDrive, Rclone, or qBittorrent links are handled. This could involve integrating a Mega-specific download utility (e.g., megadl or the Mega SDK).

Here’s a step-by-step approach to fix this:

    Add a Mega.nz Download Handler:
        Create a new function in bot.helper.mirror_utils.download_utils, such as add_mega_download, to handle Mega.nz links. This function could use the mega Python library (Mega SDK) or an external tool like megadl.
        Example structure:
        python

    async def add_mega_download(mirror_obj: Mirror, path: str):
        try:
            LOGGER.info(f"Downloading Mega.nz link: {mirror_obj.link}")
            # Example: Use megadl or Mega SDK
            from mega import Mega
            mega = Mega()
            m = mega.login()  # Add credentials if needed
            m.download_url(mirror_obj.link, dest_path=path)
            LOGGER.info("Mega.nz download completed")
        except Exception as e:
            LOGGER.error(f"Mega.nz download failed: {e}")
            await editMessage(f"ERROR: Failed to download Mega.nz link: {e}", mirror_obj.editable)
            mirror_obj.removeFromSameDir()

Modify the newEvent Method:

    Add a condition to handle Mega.nz links explicitly before the default aria2c fallback.
    Update the relevant section of the newEvent method:
    python

    elif is_gdrive_link(self.link) or is_gdrive_id(self.link):
        await add_gd_download(self, path)
    elif is_mega_link(self.link):  # Add this condition
        await add_mega_download(self, path)
    elif self.isQbit:
        await add_qb_torrent(self, path, ratio, seed_time)
    else:
        ussr, pssw = args['-au'], args['-ap']
        if ussr or pssw:
            auth = f'{ussr}:{pssw}'
            headers += f" authorization: Basic {b64encode(auth.encode()).decode('ascii')}"
        if 'static.romsget.io' in self.link:
            headers = 'Referer: https://www.romsget.io/'
        await add_aria2c_download(self, path, headers, ratio, seed_time)

Install Mega.nz Dependencies:

    If using the Mega SDK, install the mega.py library:
    bash

        pip install mega.py
        Alternatively, if using megadl, ensure it’s installed and accessible in the bot’s environment.
    Test the Implementation:
        Test with a sample Mega.nz link to ensure the new handler works correctly and downloads the file to the specified path.
        Verify that the download does not fall back to aria2c.

Additional Considerations

    Authentication: Mega.nz links may require authentication (e.g., for private links). Ensure the add_mega_download function supports user credentials or API keys, possibly passed via command-line arguments (-au for username, -ap for password, as already present in the code).
    Rate Limits: Mega.nz imposes download quotas for free accounts. Handle rate-limit errors gracefully in the add_mega_download function and inform the user via editMessage.
    Error Handling: Ensure robust error handling for cases like invalid links, expired links, or network issues.
    Logging: Use the LOGGER to log download progress and errors for debugging.

Alternative Approach

If integrating a Mega.nz-specific downloader is not feasible, you could modify the direct_link_generator function (called earlier in the code) to generate a direct HTTP link for Mega.nz files, which aria2c could then handle. However, this is less reliable because Mega.nz direct links are often temporary and may still require special handling for decryption keys.
Conclusion

Mega.nz links are being downloaded with aria2c because the code lacks a dedicated handler for Mega.nz links, causing them to fall back to the default aria2c downloader. To fix this, implement a specific add_mega_download function and add a condition in the newEvent method to route Mega.nz links to it. This will ensure proper handling of Mega.nz links using a suitable tool or library, avoiding the inappropriate use of aria2c.
i have this but it rather than use arias2 kindly see the error if you need other file i will upload

mega_listener.py

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

    async def cancel_task(self):
        self.is_cancelled = True
        await self.listener.on_download_error("Download Canceled by user")

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
                


aria2_listener.py
from asyncio import gather, sleep
from time import time

from bot import aria2, task_dict, task_dict_lock, config_dict, LOGGER
from bot.helper.ext_utils.bot_utils import bt_selection_buttons, new_thread, sync_to_async
from bot.helper.ext_utils.files_utils import clean_unwanted, clean_target
from bot.helper.ext_utils.status_utils import get_readable_file_size, getTaskByGid
from bot.helper.ext_utils.task_manager import stop_duplicate_check, check_limits_size
from bot.helper.mirror_utils.status_utils.aria_status import Aria2Status
from bot.helper.telegram_helper.message_utils import sendMessage, deleteMessage, sendingMessage, update_status_message


@new_thread
async def _onDownloadStarted(api, gid):
    download = await sync_to_async(api.get_download, gid)
    if download.options.follow_torrent == 'false':
        return
    if download.is_metadata:
        LOGGER.info('onDownloadStarted: %s METADATA', gid)
        await sleep(1)
        if task := await getTaskByGid(gid):
            if task.listener.select:
                meta = await sendMessage('<i>Downloading <b>Metadata</b>, please wait...</i>', task.listener.message)
                while True:
                    await sleep(0.5)
                    if download.is_removed or download.followed_by_ids:
                        await deleteMessage(meta)
                        break
                    download = download.live
        return
    LOGGER.info('onDownloadStarted: %s - Gid: %s', download.name, gid)
    task = None
    await sleep(1)
    if task := await getTaskByGid(gid):
        download = await sync_to_async(api.get_download, gid)
        await sleep(2)
        download = download.live
        task.listener.name = download.name
        file, name = await stop_duplicate_check(task.listener)
        if file:
            LOGGER.info('File/folder already in Drive!')
            task.listener.name = name
            await task.listener.onDownloadError('File/folder already in Drive!', file)
            await sync_to_async(api.remove, [download], force=True, files=True)
            return

        size = download.total_length
        if msg := await check_limits_size(task.listener, size):
            LOGGER.info('File/folder size over the limit size!')
            await gather(task.listener.onDownloadError(f'{msg}. File/folder size is {get_readable_file_size(size)}.'),
                         sync_to_async(api.remove, [download], force=True, files=True))


@new_thread
async def _onDownloadComplete(api, gid):
    try:
        download = await sync_to_async(api.get_download, gid)
    except:
        return
    if download.options.follow_torrent == 'false':
        return
    if download.followed_by_ids:
        new_gid = download.followed_by_ids[0]
        LOGGER.info('Gid changed from %s to %s', gid, new_gid)
        await sleep(1.5)
        task = await getTaskByGid(new_gid)
        if task := await getTaskByGid(new_gid):
            if config_dict['BASE_URL'] and task.listener.select:
                if not task.queued:
                    await sync_to_async(api.client.force_pause, new_gid)
                SBUTTONS = bt_selection_buttons(new_gid)
                msg = f'<code>{task.name()}</code>\n\n{task.listener.tag}, your download paused. Choose files then press <b>Done Selecting</b> button to start downloading.'
                await sendingMessage(msg, task.listener.message, config_dict['IMAGE_PAUSE'], SBUTTONS)
    elif download.is_torrent:
        if task := await getTaskByGid(gid):
            if hasattr(task, 'listener') and task.seeding:
                LOGGER.info('Cancelling Seed: %s onDownloadComplete')
                await gather(task.listener.onUploadError(f'Seeding stopped with Ratio {task.ratio()} ({task.seeding_time()})'),
                             sync_to_async(api.remove, [download], force=True, files=True))
    else:
        LOGGER.info('onDownloadComplete: %s - Gid: %s', download.name, gid)
        if task := await getTaskByGid(gid):
            await task.listener.onDownloadComplete()
            await sync_to_async(api.remove, [download], force=True, files=True)


@new_thread
async def _onBtDownloadComplete(api, gid):
    seed_start_time = time()
    await sleep(1)
    download = await sync_to_async(api.get_download, gid)
    if download.options.follow_torrent == 'false':
        return
    LOGGER.info('onBtDownloadComplete: %s - Gid: %s', download.name, gid)
    task = await getTaskByGid(gid)
    if not task:
        return

    if task.listener.select:
        res = download.files
        await gather(*[clean_target(file_o.path) for file_o in res if not file_o.selected])
        await clean_unwanted(download.dir)

    if task.listener.seed:
        try:
            await sync_to_async(api.set_options, {'max-upload-limit': '0'}, [download])
        except Exception as e:
            LOGGER.error('%s You are not able to seed because you added global option seed-time=0 without adding specific seed_time for this torrent GID: %s', e, gid)
    else:
        try:
            await sync_to_async(api.client.force_pause, gid)
        except Exception as e:
            LOGGER.error('%s GID: %s', e, gid)

    await task.listener.onDownloadComplete()
    download = download.live
    if task.listener.seed:
        if download.is_complete:
            if task := await getTaskByGid(gid):
                LOGGER.info('Cancelling Seed: %s', download.name)
                await gather(task.listener.onUploadError(f'Seeding stopped with Ratio {task.ratio()} ({task.seeding_time()})'),
                             sync_to_async(api.remove, [download], force=True, files=True))
        else:
            async with task_dict_lock:
                if task.listener.mid not in task_dict:
                    await sync_to_async(api.remove, [download], force=True, files=True)
                    return
                task_dict[task.listener.mid] = Aria2Status(task.listener, gid, True)
                task_dict[task.listener.mid].start_time = seed_start_time
            LOGGER.info('Seeding started: %s - Gid: %s', download.name, gid)
            await update_status_message(task.listener.message.chat.id)
    else:
        await sync_to_async(api.remove, [download], force=True, files=True)


@new_thread
async def _onDownloadStopped(api, gid):
    await sleep(4)
    if task := await getTaskByGid(gid):
        task.listene.name = task.name().replace('[METADATA]', '')
        await task.listener.onDownloadError('Dead torrent!')


@new_thread
async def _onDownloadError(api, gid):
    LOGGER.error('onDownloadError: %s', gid)
    error = 'None'
    try:
        download = await sync_to_async(api.get_download, gid)
        if download.options.follow_torrent == 'false':
            return
        error = download.error_message
        raise ValueError(error)
    except Exception as e:
        LOGGER.error('Failed to get download: %s', e)

    if task := await getTaskByGid(gid):
        task.listener.name = task.name().replace('[METADATA]', '')
        await task.listener.onDownloadError(error)


def start_aria2_listener():
    aria2.listen_to_notifications(threaded=False,
                                  on_download_start=_onDownloadStarted,
                                  on_download_error=_onDownloadError,
                                  on_download_stop=_onDownloadStopped,
                                  on_download_complete=_onDownloadComplete,
                                  on_bt_download_complete=_onBtDownloadComplete,
                                  timeout=60)

From the code and context provided, it appears that Mega.nz links are intended to be handled by a Mega-specific downloader (as implemented in mega_listener.py), but they are still being routed to aria2c for downloading. Additionally, you mentioned an error but didn't specify its details. I'll analyze the provided code to identify why Mega.nz links are being processed by aria2c instead of the Mega downloader and highlight potential issues in mega_listener.py that could cause errors. If you have a specific error message or additional files (e.g., the implementation of add_mega_download), please share them for a more precise diagnosis.
Why Mega.nz Links Are Using Aria2c

The issue likely originates in the Mirror class's newEvent method (from your first code snippet) and its interaction with the Mega.nz download logic. Let's revisit the relevant section:
python
if is_mega_link(self.link):
    self.isJd = False

This condition correctly identifies Mega.nz links and disables JDownloader (isJd). However, the code does not explicitly call a Mega-specific download function (e.g., add_mega_download) after this check. Instead, it proceeds through other conditions, and if none match, it falls back to the default add_aria2c_download handler:
python
else:
    ussr, pssw = args['-au'], args['-ap']
    if ussr or pssw:
        auth = f'{ussr}:{pssw}'
        headers += f" authorization: Basic {b64encode(auth.encode()).decode('ascii')}"
    if 'static.romsget.io' in self.link:
        headers = 'Referer: https://www.romsget.io/'
    await add_aria2c_download(self, path, headers, ratio, seed_time)

Since you have a mega_listener.py file, it suggests that a Mega-specific downloader exists, likely implemented in a function like add_mega_download (possibly in bot.helper.mirror_utils.download_utils.mega_download). However, the newEvent method is not routing Mega.nz links to this function. This could happen for the following reasons:

    Missing or Incorrect Condition for Mega.nz:
        The newEvent method may not include an explicit call to add_mega_download for Mega.nz links. For example, it should have something like:
        python

        elif is_mega_link(self.link):
            await add_mega_download(self, path)
        If this is missing, Mega.nz links fall through to the else block, which uses aria2c.
    Error in Mega Downloader:
        If add_mega_download is called but encounters an error (e.g., login failure, invalid link, or API issue), it might raise an exception that causes the download to fail silently or revert to another handler. The mega_listener.py code includes retry logic for "Access denied" errors, but other errors might not be handled gracefully, potentially causing the bot to fall back to aria2c or terminate the task.
    Link Misidentification:
        The is_mega_link function (in bot.helper.ext_utils.links_utils) might not correctly identify some Mega.nz links, causing them to be treated as generic URLs and passed to aria2c. For example, if a Mega.nz link is malformed or uses a non-standard format, it might not match the expected pattern.
    Configuration or Conditional Logic:
        There might be a configuration setting (e.g., in config_dict) or additional logic in add_mega_download that skips Mega.nz handling under certain conditions (e.g., missing credentials, disabled Mega support, or premium user checks).

Analysis of mega_listener.py

The mega_listener.py file implements a listener for the Mega.nz API, handling login, download events, and retries. It appears to be part of the Mega download process, likely used by add_mega_download. Let's review it for potential issues that could cause errors or prevent successful downloads, which might indirectly lead to falling back to aria2c.
Key Components

    AsyncExecutor: Wraps synchronous Mega API calls in an asynchronous context using sync_to_async and async_to_sync.
    mega_login: Handles Mega.nz login with retry logic for failed attempts.
    mega_logout: Logs out from the Mega API.
    perform_account_activation_tasks: Performs post-login tasks to "activate" the account (e.g., fetching root node, account info).
    MegaAppListener: A Mega API listener that handles request and transfer events, including errors and retries.

Potential Issues in mega_listener.py

    Login Failures:
        The mega_login function retries login up to max_retries times with exponential backoff:
        python

async def mega_login(executor, api, MAIL, PASS, max_retries=3, retry_delay=5):
    for attempt in range(max_retries):
        try:
            LOGGER.info("Attempting to log in to Mega...")
            await sync_to_async(executor.do, api.login, (MAIL, PASS))
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
Issue: The except Exception as e is too broad, catching all exceptions without distinguishing between transient errors (e.g., network issues) and fatal errors (e.g., invalid credentials). If login fails due to incorrect MAIL or PASS, the function will retry unnecessarily and eventually return False, causing the download to fail.
Impact: If add_mega_download relies on mega_login and login fails, it might raise an exception or terminate the task, potentially causing the bot to skip Mega handling and fall back to aria2c (if fallback logic exists in add_mega_download).
Fix: Catch specific Mega API exceptions (e.g., MegaError with error codes like MegaError.API_EACCESS or MegaError.API_EARGS) and handle them appropriately. For example:
python

    from mega import MegaError
    async def mega_login(executor, api, MAIL, PASS, max_retries=3, retry_delay=5):
        for attempt in range(max_retries):
            try:
                LOGGER.info("Attempting to log in to Mega...")
                await sync_to_async(executor.do, api.login, (MAIL, PASS))
                LOGGER.info("Successfully logged in to Mega.")
                await perform_account_activation_tasks(api, executor)
                return True
            except MegaError as e:
                if e.getCode() in [MegaError.API_EACCESS, MegaError.API_EAGAIN]:
                    LOGGER.error(f"Login failed (Attempt {attempt + 1}/{max_retries}): {e}")
                    if attempt < max_retries - 1:
                        time.sleep(retry_delay)
                        retry_delay *= 2
                    else:
                        LOGGER.error("Max login retries reached.")
                        return False
                else:
                    LOGGER.error(f"Fatal login error: {e}")
                    return False
            except Exception as e:
                LOGGER.error(f"Unexpected error during login: {e}")
                return False

Retry Logic in MegaAppListener:

    The _retry_transfer method handles "Access denied" errors by attempting to re-login and re-initiate the transfer:
    python

async def _retry_transfer(self, error_message, max_retries=3, retry_delay=5):
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
Issue: The method assumes self._transfer exists and can be retried, but it doesn't actually re-initiate the transfer (the commented-out section suggests uncertainty about how to do this). Without re-initiating the transfer, retries will fail.
Impact: If a transfer fails due to "Access denied" and retries don't work, the download task may terminate, potentially causing the bot to fall back to aria2c if add_mega_download has fallback logic.
Fix: Implement the transfer re-initiation logic. For example, if downloading a URL, re-call api.startDownload with the same parameters:
python

    async def _retry_transfer(self, error_message, max_retries=3, retry_delay=5):
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
                # Re-initiate the transfer
                await sync_to_async(self.mega_api.startDownload, self._transfer.getNode(), self._transfer.getDestPath(), None, None, False, None, self)
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
    Ensure the correct Mega API method is used based on how add_mega_download initiates downloads.

Error Handling in Event Callbacks:

    Methods like onRequestFinish, onRequestTemporaryError, onTransferUpdate, onTransferFinish, and onTransferTemporaryError handle Mega API events. Some lack robust error handling or logging:
    python

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
Issue: The except Exception as e catches all errors but only logs them without setting self.error or notifying the listener, which could leave the download in an inconsistent state.
Impact: If an error occurs during transfer completion, the task might hang or fail silently, potentially triggering a fallback to aria2c if add_mega_download retries with a different method.
Fix: Enhance error handling to notify the listener and set self.error:
python

    def onTransferFinish(self, api: MegaApi, transfer, error):
        try:
            if self.is_cancelled:
                self.continue_event.set()
                return
            if error and str(error).lower() != "no error":
                self.error = f"Transfer error: {error}"
                async_to_sync(self.listener.on_download_error, self.error)
                self.continue_event.set()
                return
            if (
                transfer.isFinished()
                and (
                    transfer.isFolderTransfer() or
                    transfer.getFileName() == self._name
                )
            ):
                async_to_sync(self.listener.on_download_complete)
                self.continue_event.set()
        except Exception as e:
            LOGGER.error(f"Error in onTransferFinish: {e}")
            self.error = str(e)
            async_to_sync(self.listener.on_download_error, f"Unexpected error: {e}")
            self.continue_event.set()

Thread Safety:

    The mega_lock is used in onRequestFinish but not consistently across other methods. If multiple Mega downloads run concurrently, race conditions could occur.
    Fix: Use mega_lock in all critical sections where Mega API state is modified or accessed.

Missing Transfer Object:

    The _retry_transfer method checks if self._transfer is None, but self._transfer is never set in the provided code. This suggests a missing initialization in add_mega_download or elsewhere.
    Fix: Ensure self._transfer is set when initiating a download in add_mega_download. For example:
    python

        # In add_mega_download
        listener = MegaAppListener(continue_event, mirror_obj, mega_api, executor, email, password)
        transfer = mega_api.startDownload(node, path, None, None, False, None, listener)
        listener._transfer = transfer  # Set the transfer object

Analysis of aria2_listener.py

The aria2_listener.py file handles Aria2c download events and is not directly responsible for routing Mega.nz links to aria2c. However, it confirms that Aria2c is being used for downloads, as seen in callbacks like _onDownloadStarted and _onDownloadComplete. If Mega.nz links are reaching these callbacks, it’s because they were incorrectly passed to add_aria2c_download in the newEvent method.
Suggested Fixes

To ensure Mega.nz links use the Mega downloader and avoid aria2c, apply these changes:

    Update newEvent in Mirror Class:
        Add an explicit handler for Mega.nz links in bot/mirror.py:
        python

    elif is_gdrive_link(self.link) or is_gdrive_id(self.link):
        await add_gd_download(self, path)
    elif is_mega_link(self.link):
        await add_mega_download(self, path)
    elif self.isQbit:
        await add_qb_torrent(self, path, ratio, seed_time)
    Ensure add_mega_download is defined in bot.helper.mirror_utils.download_utils.mega_download and uses mega_listener.py.

Implement add_mega_download:

    If not already present, create add_mega_download to use the Mega API and MegaAppListener. Example:
    python

    from mega import MegaApi
    from bot.helper.mirror_utils.download_utils.mega_listener import MegaAppListener, AsyncExecutor, mega_login
    from threading import Event

    async def add_mega_download(mirror_obj: Mirror, path: str):
        try:
            mega_api = MegaApi(None, None, None, 'YourAppName')
            executor = AsyncExecutor()
            continue_event = Event()
            email = mirror_obj.user_dict.get('mega_email', 'your_email')  # From config or args
            password = mirror_obj.user_dict.get('mega_password', 'your_password')  # From config or args
            
            # Login
            login_success = await mega_login(executor, mega_api, email, password)
            if not login_success:
                await mirror_obj.editable.edit("Failed to log in to Mega.nz")
                mirror_obj.removeFromSameDir()
                return
            
            # Initialize listener
            listener = MegaAppListener(continue_event, mirror_obj, mega_api, executor, email, password)
            
            # Parse Mega link and get node
            mega_api.getPublicNode(mirror_obj.link, listener)
            continue_event.wait()
            if listener.error:
                await mirror_obj.editable.edit(f"Error: {listener.error}")
                mirror_obj.removeFromSameDir()
                return
            node = listener.public_node
            if not node:
                await mirror_obj.editable.edit("Error: Could not retrieve Mega.nz node")
                mirror_obj.removeFromSameDir()
                return
            
            # Start download
            transfer = mega_api.startDownload(node, path, None, None, False, None, listener)
            listener._transfer = transfer  # Set transfer for retries
            continue_event.wait()
            
            if listener.error:
                await mirror_obj.editable.edit(f"Download failed: {listener.error}")
                mirror_obj.removeFromSameDir()
            elif listener.is_cancelled:
                await mirror_obj.editable.edit("Download cancelled")
                mirror_obj.removeFromSameDir()
            else:
                await mirror_obj.editable.edit("Download completed successfully")
            
            # Logout
            await mega_logout(executor, mega_api)
        except Exception as e:
            LOGGER.error(f"Mega download error: {e}")
            await mirror_obj.editable.edit(f"Error: {e}")
            mirror_obj.removeFromSameDir()

Fix mega_listener.py:

    Apply the fixes suggested above (specific exception handling, transfer re-initiation, robust error handling).
    Ensure self._transfer is set in add_mega_download.

Check is_mega_link:

    Verify that is_mega_link in bot.helper.ext_utils.links_utils correctly identifies Mega.nz[Mega.nz URLs. Example:
    python

        def is_mega_link(link):
            return bool(re.match(r'https?://mega\.(nz|co\.nz)/(#!|folder/|file/)[^\s]+', link))
    Debugging:
        Add logging in newEvent to confirm whether is_mega_link returns True for your test links.
        Log the flow of the download process to ensure add_mega_download is called and completes successfully.

Request for Additional Information

To provide a more precise diagnosis, please share:

    The specific error message you’re encountering when downloading Mega.nz links.
    The implementation of add_mega_download (likely in bot.helper.mirror_utils.download_utils.mega_download.py).
    A sample Mega.nz link that’s being incorrectly handled by aria2c.
    Any relevant logs from LOGGER output showing the download process or errors.

Conclusion

Mega.nz links are being handled by aria2c because the newEvent method lacks an explicit call to add_mega_download for Mega.nz links, causing them to fall back to the default aria2c handler. Additionally, potential issues in mega_listener.py (e.g., login failures, missing transfer re-initiation, broad exception handling) could cause Mega downloads to fail, possibly triggering a fallback. By adding a Mega.nz handler in newEvent, implementing add_mega_download, and fixing mega_listener.py, you can ensure Mega.nz links are processed correctly. Please provide the requested details for further assistance.
add_mega_download try with this and give me full code what to do and if you need more files from code tell me 

Thank you for providing the context and the mega_listener.py and aria2_listener.py files. The issue is that Mega.nz links are being routed to aria2c instead of a Mega-specific downloader, likely due to missing or incorrect handling in the Mirror class's newEvent method. You’ve asked for the implementation of add_mega_download and the full code to fix the issue. Below, I’ll provide a complete solution, including:

    An implementation of add_mega_download to handle Mega.nz downloads using the Mega API and mega_listener.py.
    Modifications to the Mirror class’s newEvent method to route Mega.nz links to add_mega_download.
    Updates to mega_listener.py to address potential issues (e.g., login failures, retry logic, error handling).
    Instructions for integrating these changes and testing.

If additional files are needed (e.g., bot.helper.ext_utils.links_utils for is_mega_link or bot.helper.mirror_utils.download_utils structure), I’ll specify them. Since you haven’t shared a specific error message, I’ll assume the primary issue is the routing to aria2c and potential failures in the Mega downloader due to unhandled errors or missing transfer re-initiation.
Solution Overview

    Goal: Ensure Mega.nz links are handled by a dedicated add_mega_download function instead of aria2c.
    Steps:
        Implement add_mega_download in bot/helper/mirror_utils/download_utils/mega_download.py.
        Update the newEvent method in bot/mirror.py to call add_mega_download for Mega.nz links.
        Enhance mega_listener.py to fix retry logic, error handling, and transfer initialization.
        Verify dependencies and configuration (e.g., Mega credentials, Mega API setup).
        Provide testing instructions and debugging tips.

Assumptions

    The Mega API is provided by the mega library (mega.py), which you’re using in mega_listener.py.
    Mega credentials (email and password) are available via mirror_obj.user_dict or config_dict.
    The is_mega_link function in bot.helper.ext_utils.links_utils correctly identifies Mega.nz URLs (e.g., https://mega.nz/#!... or https://mega.nz/file/...).
    The TaskListener class (parent of Mirror) handles download events (e.g., on_download_complete, on_download_error).

If any of these assumptions are incorrect or if additional files are needed (e.g., links_utils.py, config_dict structure, or TaskListener implementation), please provide them.
Step 1: Implement add_mega_download

Create or update bot/helper/mirror_utils/download_utils/mega_download.py with the following implementation. This function initializes the Mega API, logs in, downloads the file using MegaAppListener, and handles errors.
mega_download.py
python

Notes:

    This implementation uses the Mega API to download public links (identified by mirror_obj.link).
    Credentials are retrieved from mirror_obj.user_dict or config_dict. Adjust the keys (mega_email, mega_password) based on your configuration.
    The MegaAppListener from mega_listener.py handles download events and retries.
    The download path and file name are set based on mirror_obj attributes, consistent with other download handlers (e.g., add_gd_download).

Step 2: Update Mirror Class’s newEvent Method

Modify bot/mirror.py to route Mega.nz links to add_mega_download. The change involves adding an elif condition in the download handler section of the newEvent method.
mirror.py
python

Changes Made:

    Added from bot.helper.mirror_utils.download_utils.mega_download import add_mega_download to the imports.
    Inserted await add_mega_download(self, path) after if is_mega_link(self.link): self.isJd = False.
    Kept the redundant elif is_mega_link(self.link) for clarity, but it’s not strictly necessary since the earlier condition handles Mega.nz links.
    Ensured the else block (calling add_aria2c_download) is only reached for non-Mega.nz links.

Step 3: Update mega_listener.py

The provided mega_listener.py has issues with retry logic, error handling, and transfer initialization. Below is an updated version with fixes to ensure robust Mega.nz downloads.
mega_listener.py
python

Changes Made:

    Specific Exception Handling: In mega_login, catch MegaError for specific error codes (e.g., API_EACCESS, API_EAGAIN) to distinguish between retryable and fatal errors.
    Robust Error Handling: In onTransferFinish and onRequestFinish, ensure errors are propagated to the listener via on_download_error.
    Transfer Re-initiation: In _retry_transfer, re-initiate the download using the same node, path, and file name from the original transfer.
    Thread Safety: Ensured mega_lock is used in critical sections.
    Logging: Improved logging for debugging (e.g., error codes, transfer details).

Step 4: Verify Dependencies and Configuration

    Install Mega.py: Ensure the mega.py library is installed:
    bash

pip install mega.py
Configure Mega Credentials:

    Add Mega.nz credentials to config_dict in bot/config.py or your configuration file:
    python

config_dict = {
    'MEGA_EMAIL': 'your_email@example.com',
    'MEGA_PASSWORD': 'your_password',
    # ... other config options
}
Alternatively, allow users to provide credentials via command-line arguments (-au for email, -ap for password) by updating arg_base in newEvent:
python
arg_base = {
    # ... other args
    '-au': '',  # Mega email
    '-ap': '',  # Mega password
}
Then, in add_mega_download, use:
python

    email = mirror_obj.user_dict.get('mega_email', args.get('-au', config_dict.get('MEGA_EMAIL')))
    password = mirror_obj.user_dict.get('mega_password', args.get('-ap', config_dict.get('MEGA_PASSWORD')))

Verify is_mega_link: Ensure is_mega_link in bot/helper/ext_utils/links_utils.py correctly identifies Mega.nz URLs. Example:
python

    import re

    def is_mega_link(link):
        return bool(re.match(r'https?://mega\.(nz|co\.nz)/(#!|folder/|file/)[^\s]+', link))
    If this function is incorrect or missing, Mega.nz links may not be detected, causing them to fall back to aria2c. Please share links_utils.py if you suspect issues here.

Step 5: Testing Instructions

    Deploy the Changes:
        Save mega_download.py, mirror.py, and mega_listener.py in their respective locations.
        Restart the bot to apply the changes.
    Test with a Mega.nz Link:
        Use a command like:
        text

/mirror https://mega.nz/file/abc123#def456
Optionally, provide credentials:
text

    /mirror https://mega.nz/file/abc123#def456 -au your_email@example.com -ap your_password

Monitor Logs:

    Check the logs (via LOGGER) for messages like:
        Starting Mega.nz download: <file_name> to <path>
        Successfully logged in to Mega.
        Mega.nz download completed: <file_name>
    Look for errors like Failed to log in to Mega.nz or Error retrieving Mega.nz node.

Debugging Tips:

    If the download still uses aria2c, add a log in newEvent to verify is_mega_link:
    python

if self.link:
    LOGGER.info(f"Link: {self.link}, is_mega_link: {is_mega_link(self.link)}")
If the Mega download fails, check for specific error messages in the logs and share them.
Verify that add_mega_download is called by adding a log:
python

        LOGGER.info("Calling add_mega_download for Mega.nz link")
        await add_mega_download(self, path)

Potential Additional Files Needed

Based on the analysis, the following files might be needed to fully resolve the issue:

    bot/helper/ext_utils/links_utils.py: To verify the is_mega_link function.
    bot/config.py: To confirm how config_dict is structured and whether Mega credentials are provided.
    bot/helper/listeners/tasks_listener.py: To ensure TaskListener methods (on_download_complete, on_download_error) are compatible with MegaAppListener.
    bot/helper/mirror_utils/download_utils/init.py: To confirm all download utilities are correctly imported.

If you encounter errors or the Mega.nz links still use aria2c, please provide:

    The specific error message from the logs.
    The content of links_utils.py or confirmation that is_mega_link works.
    A sample Mega.nz link that fails.
    Any additional files listed above if relevant.

Conclusion

The provided solution implements add_mega_download, updates mirror.py to route Mega.nz links correctly, and enhances mega_listener.py for robust error handling and retries. By applying these changes, Mega.nz links should be handled by the Mega API instead of aria2c. Ensure Mega credentials are configured and test thoroughly. If issues persist, share the requested details for further assistance.
