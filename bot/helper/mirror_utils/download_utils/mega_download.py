from mega import MegaApi, MegaError
from threading import Event
from bot import LOGGER, config_dict
from bot.helper.mirror_utils.download_utils.mega_listener import MegaAppListener, AsyncExecutor, mega_login, mega_logout
from bot.helper.ext_utils.bot_utils import sync_to_async, arg_parser
from bot.helper.telegram_helper.message_utils import editMessage

async def add_mega_download(mirror_obj, path: str):
    """Download a Mega.nz link using the Mega API."""
    try:
        LOGGER.info(f"Starting Mega.nz download for link: {mirror_obj.link}")
        # Initialize Mega API
        mega_api = MegaApi(None, None, None, 'MirrorBot')
        executor = AsyncExecutor()
        continue_event = Event()
        
        # Get Mega credentials from args, user_dict, or config_dict
        args = arg_parser(mirror_obj.message.text.split(' ')[1:], {
            '-au': '',  # Mega email
            '-ap': ''   # Mega password
        })
        email = args.get('-au') or mirror_obj.user_dict.get('mega_email', config_dict.get('MEGA_EMAIL'))
        password = args.get('-ap') or mirror_obj.user_dict.get('mega_password', config_dict.get('MEGA_PASSWORD'))
        
        if not email or not password:
            error_msg = "Mega.nz credentials not provided. Use -au <email> -ap <password> or set MEGA_EMAIL and MEGA_PASSWORD in config."
            LOGGER.error(error_msg)
            await editMessage(error_msg, mirror_obj.editable)
            mirror_obj.removeFromSameDir()
            await mirror_obj.onDownloadError(error_msg)
            return
        
        # Login to Mega
        LOGGER.info("Attempting Mega.nz login")
        login_success = await mega_login(executor, mega_api, email, password)
        if not login_success:
            error_msg = "Failed to log in to Mega.nz. Check credentials."
            LOGGER.error(error_msg)
            await editMessage(error_msg, mirror_obj.editable)
            mirror_obj.removeFromSameDir()
            await mirror_obj.onDownloadError(error_msg)
            return
        
        # Initialize listener
        listener = MegaAppListener(continue_event, mirror_obj, mega_api, executor, email, password)
        
        # Get public node from Mega link
        LOGGER.info("Retrieving Mega.nz public node")
        await sync_to_async(mega_api.getPublicNode, mirror_obj.link, listener)
        continue_event.wait()
        if listener.error:
            error_msg = f"Error retrieving Mega.nz node: {listener.error}"
            LOGGER.error(error_msg)
            await editMessage(error_msg, mirror_obj.editable)
            mirror_obj.removeFromSameDir()
            await mirror_obj.onDownloadError(error_msg)
            await mega_logout(executor, mega_api)
            return
        
        node = listener.public_node
        if not node:
            error_msg = "Error: Could not retrieve Mega.nz node."
            LOGGER.error(error_msg)
            await editMessage(error_msg, mirror_obj.editable)
            mirror_obj.removeFromSameDir()
            await mirror_obj.onDownloadError(error_msg)
            await mega_logout(executor, mega_api)
            return
        
        # Set download name if specified
        if mirror_obj.name:
            file_name = mirror_obj.name
        else:
            file_name = node.getName()
        
        # Start download
        LOGGER.info(f"Starting Mega.nz download: {file_name} to {path}")
        transfer = mega_api.startDownload(node, path, file_name, None, False, None, listener)
        listener._transfer = transfer  # Set transfer for retries
        continue_event.wait()
        
        if listener.error:
            error_msg = f"Download failed: {listener.error}"
            LOGGER.error(error_msg)
            await editMessage(error_msg, mirror_obj.editable)
            mirror_obj.removeFromSameDir()
            await mirror_obj.onDownloadError(error_msg)
        elif listener.is_cancelled:
            LOGGER.info("Mega.nz download cancelled by user")
            await editMessage("Download cancelled by user.", mirror_obj.editable)
            mirror_obj.removeFromSameDir()
            await mirror_obj.onDownloadError("Download cancelled by user")
        else:
            LOGGER.info(f"Mega.nz download completed: {file_name}")
            await mirror_obj.onDownloadComplete()
        
        # Logout
        await mega_logout(executor, mega_api)
    
    except MegaError as e:
        error_msg = f"Mega API error: {e} (Code: {e.getCode()})"
        LOGGER.error(error_msg)
        await editMessage(error_msg, mirror_obj.editable)
        mirror_obj.removeFromSameDir()
        await mirror_obj.onDownloadError(error_msg)
        await mega_logout(executor, mega_api)
    except Exception as e:
        error_msg = f"Unexpected error in Mega.nz download: {e}"
        LOGGER.error(error_msg, exc_info=True)
        await editMessage(error_msg, mirror_obj.editable)
        mirror_obj.removeFromSameDir()
        await mirror_obj.onDownloadError(error_msg)
        await mega_logout(executor, mega_api)