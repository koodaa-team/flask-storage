import os
import itertools

from werkzeug.utils import secure_filename


__all__ = ('Storage')


def reraise(exception):
    kwargs = {
        'message': exception.message,
        'wrapped_exception': exception
    }
    # cloudfiles and S3Boto exceptions have http compatible status codes we
    # need to assign them to StorageException
    if hasattr(exception, 'status'):
        kwargs['status_code'] = exception.status

        if kwargs['status_code'] == 404:
            raise FileNotFoundError(**kwargs)
        elif kwargs['status_code'] == 409:
            raise FileExistsError(**kwargs)

    raise StorageException(**kwargs)


def safe_join(base, *paths):
    """
    A version of django.utils._os.safe_join for S3 paths.

    Joins one or more path components to the base path component
    intelligently. Returns a normalized version of the final path.

    The final path must be located inside of the base path component
    (otherwise a ValueError is raised).

    Paths outside the base path indicate a possible security
    sensitive operation.
    """
    from urllib.parse import urljoin
    #base_path = force_unicode(base)
    base_path = str(base)
    base_path = base_path.rstrip('/')
    paths = [str(p) for p in paths]

    final_path = base_path
    for path in paths:
        final_path = urljoin(final_path.rstrip('/') + "/", path.rstrip("/"))

    # Ensure final_path starts with base_path and that the next character after
    # the final path is '/' (or nothing, in which case final_path must be
    # equal to base_path).
    base_path_len = len(base_path)
    if not final_path.startswith(base_path) \
            or final_path[base_path_len:base_path_len + 1] not in ('', '/'):
        raise ValueError('the joined path is located outside of the base path'
                         ' component')

    return final_path.lstrip('/')


class StorageException(Exception):
    def __init__(self, message='', status_code=None, wrapped_exception=None):
        self.status_code = status_code
        self.message = message
        self.wrapped_exception = wrapped_exception


class FileNotFoundError(StorageException):
    pass


class ConflictError(StorageException):
    pass


class FileExistsError(StorageException):
    pass


class PermissionError(StorageException):
    pass


class Storage(object):
    """
    A base storage class, providing some default behaviors that all other
    storage systems can inherit or override, as necessary.
    """

    def open(self, name, mode='rb'):
        """
        Retrieves the specified file from storage.
        """
        return self._open(name, mode)

    def _open(self, name, mode='rb'):
        raise NotImplementedError

    def save(self, name, content, folder=None):
        """
        Saves new content to the file specified by name. The content should be
        a file-like object, ready to be read from the beginning.
        """
        filename = os.path.normpath(secure_filename(os.path.basename(name)))
        if folder is not None:
            folder = os.path.normpath(folder)
            name = safe_join(folder, filename)
        else:
            name = filename

        name = self.get_available_name(name)
        name = self._save(name, content)

        return name

    def _save(self, name, content):
        raise NotImplementedError

    def get_available_name(self, name):
        """
        Returns a filename that's free on the target storage system, and
        available for new content to be written to.
        """
        dir_name, file_name = os.path.split(name)
        file_root, file_ext = os.path.splitext(file_name)
        # If the filename already exists, add an underscore and a number
        # (before the file extension, if one exists) to the filename until the
        # generated filename doesn't exist.
        count = itertools.count(1)
        while self.exists(name):
            # file_ext includes the dot.
            newname = "%s_%s%s" % (file_root, next(count), file_ext)
            name = safe_join(dir_name, newname)
        return name

    def path(self, name):
        """
        Returns a local filesystem path where the file can be retrieved using
        Python's built-in open() function. Storage systems that can't be
        accessed using open() should *not* implement this method.
        """
        raise NotImplementedError(
            "This backend doesn't support absolute paths."
        )

    def create_folder(self, name=None):
        """
        Tries to create given folder in the storage system.

        If no name is given tries to use the folder name of this object.

        The implementation of this method varies in subclasses:
            On rackspace cloudfiles this method creates a container.
            On amazon S3 this method creates a bucket.
            On normal filesystem this method creates a folder.
        """
        raise NotImplementedError

    def delete_folder(self, name=None):
        """
        Tries to delete given folder in the storage system.

        The implementation of this method varies in subclasses:
            On rackspace cloudfiles this method deletes a container.
            On amazon S3 this method deletes a bucket.
            On normal filesystem this method deletes a folder.
        """
        raise NotImplementedError

    def delete(self, name):
        """
        Deletes the specified file from the storage system.
        """
        raise NotImplementedError

    def exists(self, name):
        """
        Returns True if a file referened by the given name already exists in
        the storage system, or False if the name is available for a new file.
        """
        raise NotImplementedError

    def url(self, name):
        """
        Returns an absolute URL where the file's contents can be accessed
        directly by a Web browser.
        """
        raise NotImplementedError

    def _clean_name(self, name):
        """
        Cleans the name so that Windows style paths work
        """
        # Useful for windows' paths
        return os.path.normpath(name).replace('\\', '/')

    def _normalize_name(self, name):
        """
        Normalizes the name so that paths like
        /path/to/ignored/../something.txt
        work. We check to make sure that the path pointed to is not outside
        the directory specified by the LOCATION setting.
        """
        try:
            return safe_join(self.location, name)
        except ValueError:
            raise StorageException("Attempted access to '%s' denied." % name)

    def _encode_name(self, name):
        return str(name)
        #return smart_str(name, encoding=self.file_name_charset)

    def _decode_name(self, name):
        return str(name)
        #return force_unicode(name, encoding=self.file_name_charset)


class StorageFile(object):
    """
    Base class for driver file classes
    """
    @property
    def url(self):
        return self._storage.url(self._key.name)

    def delete(self):
        self._storage.delete(self._key.name)

    @property
    def size(self):
        return self._file.size

    def read(self, size=None):
        if self._pos == self.size:
            return ''
        size = min(size, self.size - self._pos)
        data = self._file.read(size=size or -1, offset=self._pos)
        self._pos += len(data)
        return data

    def seek(self, offset, whence=os.SEEK_SET):
        if whence == os.SEEK_SET:
            self._pos = offset
        elif whence == os.SEEK_CUR:
            self._pos += offset
        elif whence == os.SEEK_END:
            self._pos = self.size + offset
        else:
            raise IOError(22, 'Invalid argument')

    def tell(self):
        return self._pos
