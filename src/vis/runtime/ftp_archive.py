"""FTP / network image archive uploader.

Pass an FtpUploader as the FrameArchiver `uploader` to mirror archived images to
a central FTP server (long-term retention / QA review off the line PC). A network
share is simpler still — point the FrameArchiver `directory` at the mounted share.
"""

from __future__ import annotations

import os


class FtpUploader:
    def __init__(self, host, username="", password="", remote_dir="/", port=21) -> None:
        self.host = host
        self.username = username
        self.password = password
        self.remote_dir = remote_dir
        self.port = port

    def __call__(self, local_path: str) -> str:
        from ftplib import FTP

        name = os.path.basename(local_path)
        remote = f"{self.remote_dir.rstrip('/')}/{name}"
        with FTP() as ftp:
            ftp.connect(self.host, self.port)
            ftp.login(self.username, self.password)
            with open(local_path, "rb") as f:
                ftp.storbinary(f"STOR {remote}", f)
        return f"ftp://{self.host}{remote}"
