from bot.helper.ext_utils.status_utils import MirrorStatus, get_readable_file_size, get_readable_time

class MegaDownloadStatus:
    def __init__(self, name, size, gid, mega_listener, listener):
        self.__name = name
        self.__size = size
        self.__gid = gid
        self.__mega_listener = mega_listener
        self.__listener = listener  # Store the full listener object
        self.message = listener.message  # Store the Pyrogram Message object

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
        return get_readable_time(
            (self.__size - self.__mega_listener.downloaded_bytes) / self.__mega_listener.speed
        ) if self.__mega_listener.speed else "~"

    def engine(self):
        return "Mega"

    @property
    def listener(self):
        return self.__listener  # Provide access to the listener object as a property