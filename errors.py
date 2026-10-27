"""Custom exceptions. Everything the tool raises on purpose inherits from DownloaderError."""


class DownloaderError(Exception):
    """Base class for every error this tool raises on purpose."""


class ProfileNotFound(DownloaderError):
    pass


class PrivateProfile(DownloaderError):
    pass


class BlockedByInstagram(DownloaderError):
    """Login wall, 401/403, or rate limited past our retry budget."""


class UnexpectedResponse(DownloaderError):
    """The server answered, but not in a shape we understand."""