"""Safe failures reported by adopted storage adapters."""

class StorageError(RuntimeError):
    def __init__(self, kind, message='Placement storage is unavailable.'):
        self.kind = kind
        super().__init__(message)


class StorageClosed(StorageError):
    def __init__(self):
        super().__init__('closed', 'The placement transaction is closed.')
