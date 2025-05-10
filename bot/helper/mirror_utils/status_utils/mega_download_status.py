from time import time
from bot import LOGGER
from bot.helper.ext_utils.status_utils import get_readable_file_size, get_readable_time, MirrorStatus

class MegaDownloadStatus:
    def __init__(self, name, size, gid, mega_listener, listener, download_path):
        self.__name = name
        self.__size = size
        self.__gid = gid
        self.__mega_listener = mega_listener
        self.__listener = listener  # Store the full listener object
        self.message = listener.message  # Store the Pyrogram Message object
        self.__start_time = time()  # Record the start time of the download
        self.__download_path = download_path  # Store the download path for upload
        self.__is_uploading = False  # Track upload phase

    def name(self):
        return self.__name

    def size(self):
        return get_readable_file_size(self.__size)

    def gid(self):
        return self.__gid

    def status(self):
        return MirrorStatus.STATUS_UPLOADING if self.__is_uploading else MirrorStatus.STATUS_DOWNLOADING

    def progress(self):
        try:
            if self.__size > 0:
                return f"{round(self.__mega_listener.downloaded_bytes / self.__size * 100, 2)}%"
            return "0%"
        except Exception as e:
            LOGGER.error(f"Error calculating progress: {e}")
            return "0%"

    def processed_bytes(self):
        return get_readable_file_size(self.__mega_listener.downloaded_bytes)

    def speed(self):
        return f"{get_readable_file_size(self.__mega_listener.speed)}/s"

    def eta(self):
        try:
            remaining_bytes = self.__size - self.__mega_listener.downloaded_bytes
            speed = self.__mega_listener.speed
            LOGGER.debug(f"Mega ETA - Remaining: {remaining_bytes} bytes, Speed: {speed} bytes/s")
            if speed > 0 and remaining_bytes > 0:
                eta_seconds = remaining_bytes / speed
                if eta_seconds < 86400:  # Cap ETA at 1 day to avoid unrealistic values
                    return get_readable_time(eta_seconds)
            return "~"
        except Exception as e:
            LOGGER.error(f"Mega ETA calculation failed: {e}")
            return "~"

    def elapsed(self):
        return get_readable_time(time() - self.__start_time)  # Calculate elapsed time

    def engine(self):
        return "Mega"

    @property
    def listener(self):
        return self.__listener  # Provide access to the listener object as a property

    @property
    def download_path(self):
        return self.__download_path  # Provide access to the download path

    def set_upload_phase(self):
        self.__is_uploading = True  # Switch to upload phase

    def task(self):
        return self

    async def cancel_task(self):
        LOGGER.info(f"Cancelling Mega Download: {self.__name}")
        await self.__mega_listener.cancel_task()