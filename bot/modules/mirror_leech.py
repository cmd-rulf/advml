from secrets import token_hex
from aiofiles.os import makedirs
from mega import MegaApi
from .... import LOGGER, task_dict, task_dict_lock
from ....core.config_manager import Config
from ...ext_utils.links_utils import get_mega_link_type
from ...ext_utils.bot_utils import sync_to_async
from ...ext_utils.task_manager import (
    check_running_tasks,
    stop_duplicate_check,
    limit_checker,
)
from ...mirror_leech_utils.status_utils.mega_dl_status import MegaDownloadStatus
from ...mirror_leech_utils.status_utils.queue_status import QueueStatus
from ...telegram_helper.message_utils import (
    auto_delete_message,
    delete_links,
    send_message,
    send_status_message,
)
from ...listeners.mega_listener import (
    MegaAppListener,
    AsyncMega,
)

async def add_mega_download(listener, path):
    async_api = AsyncMega()
    async_api.api = api = MegaApi(None, None, None, "SEARCH-X")
    folder_api = None

    # Pass email and password to MegaAppListener for retry logic
    mega_listener = MegaAppListener(
        async_api.continue_event,
        listener,
        api,
        email=Config.MEGA_EMAIL,
        password=Config.MEGA_PASSWORD
    )
    api.addListener(mega_listener)

    # Login if credentials are provided
    if (MEGA_EMAIL := Config.MEGA_EMAIL) and (MEGA_PASSWORD := Config.MEGA_PASSWORD):
        try:
            login_success = await async_api.login(MEGA_EMAIL, MEGA_PASSWORD)
            if not login_success:
                await listener.on_download_error("Mega login failed after retries")
                return
        except Exception as e:
            LOGGER.error(f"Mega login error: {e}")
            await listener.on_download_error(f"Mega login failed: {str(e)}")
            return

    try:
        link_type = get_mega_link_type(listener.link)
        if link_type == "file":
            await async_api.getPublicNode(listener.link)
            node = mega_listener.public_node
        else:
            async_api.folder_api = folder_api = MegaApi(None, None, None, "SEARCH-X")
            folder_api.addListener(mega_listener)
            await async_api.run(folder_api.loginToFolder, listener.link)
            LOGGER.info(
                f"Folder login node: {mega_listener.node.getName()}, Type: {mega_listener.node.getType()}"
            )
            node = await sync_to_async(folder_api.authorizeNode, mega_listener.node)
            LOGGER.info(f"Authorized node: {node.getName()}, Type: {node.getType()}")

            # Fetch children for folder downloads
            children = await sync_to_async(api.getChildren, node)
            child_nodes = [children.get(i) for i in range(children.size())]
            LOGGER.info(f"Found children: {[child.getName() for child in child_nodes]}")

        if mega_listener.error:
            await listener.on_download_error(mega_listener.error)
            await async_api.logout()
            return

        listener.name = listener.name or node.getName()
        gid = token_hex(5)

        # Check for duplicates and limits
        msg, button = await stop_duplicate_check(listener)
        if msg:
            await listener.on_download_error(msg, button)
            await async_api.logout()
            return

        listener.size = await sync_to_async(api.getSize, node)
        if limit_exceeded := await limit_checker(listener):
            await listener.on_download_error(limit_exceeded, is_limit=True)
            await async_api.logout()
            return

        # Handle task queue
        added_to_queue, event = await check_running_tasks(listener)
        if added_to_queue:
            LOGGER.info(f"Added to Queue/Download: {listener.name}")
            async with task_dict_lock:
                task_dict[listener.mid] = QueueStatus(listener, gid, "Dl")
            await listener.on_download_start()
            if listener.multi <= 1:
                await send_status_message(listener.message)
            await event.wait()
            if listener.is_cancelled:
                await async_api.logout()
                return

        async with task_dict_lock:
            task_dict[listener.mid] = MegaDownloadStatus(listener, mega_listener, gid, "dl")

        if added_to_queue:
            LOGGER.info(f"Start Queued Download from Mega: {listener.name}")
        else:
            LOGGER.info(f"Download from Mega: {listener.name}")
            await listener.on_download_start()
            if listener.multi <= 1:
                await send_status_message(listener.message)

        await makedirs(path, exist_ok=True)
        # Start download (file or folder)
        await async_api.startDownload(
            node, path, listener.name, None, False, None, 3, 2, False
        )

    except Exception as e:
        LOGGER.error(f"Error in Mega download: {e}", exc_info=True)
        await listener.on_download_error(str(e))
    finally:
        try:
            await async_api.logout()
            if folder_api:
                await sync_to_async(folder_api.logout)
        except Exception as e:
            LOGGER.error(f"Error during Mega logout: {e}")