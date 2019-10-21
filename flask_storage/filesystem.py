import errno
import os
import shutil
import io

from flask import current_app, url_for
from .base import Storage, StorageException, reraise as _reraise


def reraise(exception):
    if exception.errno == errno.EEXIST:
        exception.status = 409
    elif exception.errno == errno.ENOENT:
        exception.status = 404
    exception.message = exception.strerror
    _reraise(exception)


class FileSystemStorage(Storage):
    """
    Standard filesystem storage
    """

    def __init__(self, folder_name=None):
        if folder_name is None:
            folder_name = current_app.config.get(
                'UPLOADS_FOLDER',
                os.path.dirname(__file__)
            )
        self._folder_name = folder_name
        self._absolute_path = os.path.abspath(folder_name)

    @property
    def folder_name(self):
        return self._folder_name

    def list_folders(self):
        if not self._absolute_path:
            raise StorageException('No folder given in class constructor.')
        return [a for a in os.listdir(self._absolute_path) if os.path.isdir(os.path.join(self._absolute_path, a))]

    def list_files(self):
        if not self._absolute_path:
            raise StorageException('No folder given in class constructor.')
        return [a for a in os.listdir(self._absolute_path) if not os.path.isdir(os.path.join(self._absolute_path, a))]

    def _save(self, name, content):
        full_path = self.path(name)
        directory = os.path.dirname(full_path)
        try:
            self.create_folder(directory)
        except StorageException as e:
            if e.status_code != 409:
                raise e

        with open(full_path, 'wb') as destination:
            buffer_size = 16384
            # we should allow strings to be passed as content since the other
            # drivers support this too
            if isinstance(content, str):
                io = io.StringIO()
                io.write(content)
                content = io

            try:
                shutil.copyfileobj(content, destination, buffer_size)
            except OSError as e:
                reraise(e)
        return name

    def open(self, name, mode='rb'):
        path = self.path(name)
        try:
            return FileSystemStorageFile(self, open(path, mode))
        except IOError as e:
            reraise(e)

    def delete_folder(self, name):
        path = self.path(name)
        try:
            return shutil.rmtree(path)
        except OSError as e:
            reraise(e)

    def create_folder(self, path):
        try:
            return os.makedirs(path)
        except OSError as e:
            reraise(e)

    def delete(self, name):
        name = self.path(name)
        try:
            return os.remove(name)
        except OSError as e:
            reraise(e)

    def exists(self, name):
        return os.path.exists(self.path(name))

    def path(self, name):
        return os.path.normpath(os.path.join(self._absolute_path, name))

    def url(self, name):
        return url_for('uploads.uploaded_file', filename=name)


class FileSystemStorageFile(object):
    def __init__(self, storage, file_):
        self.decorated = file_

    @property
    def last_modified(self):
        return os.path.getmtime(self.url)

    @property
    def size(self):
        return os.path.getsize(self.url)

    @property
    def url(self):
        return self.decorated.name

    @property
    def name(self):
        return os.path.basename(self.decorated.name)

    def __getattr__(self, name):
        return getattr(self.decorated, name)
