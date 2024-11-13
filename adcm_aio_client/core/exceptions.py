class AccessionError(Exception):
    pass


class MissingParameterError(AccessionError):
    pass


class MultipleObjectsReturnedError(AccessionError):
    pass


class ObjectDoesNotExistError(AccessionError):
    pass


class InvalidArgumentError(AccessionError):
    pass
