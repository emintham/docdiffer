class Colours(object):
    INFO = 'blue'
    WARNING = 'yellow'
    ADDED = 'green'
    REMOVED = 'red'


OFFICE_IP = '206.223.185.250'


DRF_FIELD_PARAMS = (
    'read_only',
    'write_only',
    'required',
    'allow_null',
    'source',
    'default',
    'source',
)


HEADERS = (
    'field_name',
    'func_name',
) + DRF_FIELD_PARAMS
