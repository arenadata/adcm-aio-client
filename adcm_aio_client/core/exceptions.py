class AccessionError(Exception):
    pass


class MissingParameterException(AccessionError):
    pass


class MultipleObjectsReturnedError(AccessionError):
    pass


class ObjectDoesNotExistError(AccessionError):
    pass


class InvalidArgumentError(AccessionError):
    pass
