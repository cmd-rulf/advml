from time import time
from bot import LOGGER
from bot.helper.ext_utils.status_utils import MirrorStatus, get_readable_file_size, get_readable_time

class MegaDownloadStatus:
    def __init__(self, name, size, gid, mega_listener, listener):
        self.__name = name
        self.__size = size
        self.__gid = gid
        self.__mega_listener = mega_listener
        self.__listener = listener  # Store the full listener object
        self.message = listener.message  # Store the Pyrogram Message object
        self.__start_time = time()  # Record the start time of the download

    def name(self):
        return self.__name

    def size(self):
        return get_readable_file_size(self.__size)

    def gid(self):
        return self.__gid

    def status(self):
        return MirrorStatus.STATUS_DOWNLOADING

    def progress(self):
        return f"{round(self.__mega_listener.downloaded_bytes / self.__size * 100, 2)}%"

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