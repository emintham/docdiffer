from termcolor import colored

import consts


class Field(dict):
    """
    Data of a single DRF field.
    """

    DEFAULT_DRF_FIELD_KWARGS = {
        'read_only': False,
        'required': True,
        # We don't care about these two for now
        # 'write_only': False,
        # 'allow_null': False
    }

    def __init__(self, *args, **kwargs):
        super(Field, self).__init__(*args, **kwargs)

        for key, value in self.DEFAULT_DRF_FIELD_KWARGS.items():
            self.setdefault(key, value)

    def add_representation(self, condition, representation):
        if not self.get('representations'):
            self['representations'] = {}

        self['representations'][condition] = representation

    def update_representations(self, representations):
        if not self.get('representations'):
            self['representations'] = {}

        self['representations'].update(**representations)

class Fields(dict):
    """
    Data of fields of a DRF API.
    """

    ADDED_FMT_STR = "'{}': {}\n"
    REMOVED_FMT_STR = "- '{}': {}\n"
    ADDED_DYNAMIC_STR = "'{}'\n\t'{}': {}\n"
    REMOVED_DYNAMIC_STR = "'- {}'\n\t'{}': {}\n"

    @classmethod
    def get_field_name(cls, field):
        return field['field_name']

    def extend(self, iterable, overwrite=False):
        if isinstance(iterable, Fields):
            if overwrite:
                self.update(**iterable)
                return

            iterable = iterable.values()

        for field in iterable:
            self.add(field, overwrite=overwrite)

    def add(self, field, overwrite=False):
        if not field:
            return

        if not overwrite and self.get_field_name(field) in self:
            return

        self[self.get_field_name(field)] = field

    def add_representation(self, field_name, condition, representation, overwrite=False):
        if not (field_name and condition and representation):
            return

        if not field_name in self:
            self.add(Field(field_name=field_name))

        field = self.find(field_name)

        if not overwrite and condition in field.get('representations', {}):
            return

        field.add_representation(condition, representation)

    def find(self, field_name):
        return self[field_name]

    def stringify_diff(self, base):
        def fmt_added(key, val):
            return colored(self.ADDED_FMT_STR.format(key, val),
                           consts.Colours.ADDED)

        def fmt_removed(key, val):
            return colored(self.REMOVED_FMT_STR.format(key, val),
                           consts.Colours.REMOVED)

        def fmt_added_dynamic(condition, key, val):
            return colored(self.ADDED_DYNAMIC_STR.format(condition, key, val),
                           consts.Colours.ADDED)

        def fmt_removed_dynamic(condition, key, val):
            return colored(self.REMOVED_DYNAMIC_STR.format(condition, key, val),
                           consts.Colours.REMOVED)

        def fmt_representations(field, representations, format_function):
            output = ''

            for key, val in representations.iteritems():
                output += format_function(key, field, val)

            return output

        current = self.as_dict()
        previous = base.as_dict()
        keys = set(current.keys()).union(previous.keys())

        output = ''
        for key in keys:
            if key in current and key in previous:
                if current[key] == previous[key]:
                    continue

                output += fmt_removed(key, previous[key]['description'])
                output += fmt_representations(key, previous[key]['representations'], fmt_removed_dynamic)

                output += fmt_added(key, current[key]['description'])
                output += fmt_representations(key,current[key]['representations'], fmt_added_dynamic)

            elif key in current:
                output += fmt_added(key, current[key]['description'])
                output += fmt_representations(key, current[key]['representations'], fmt_added_dynamic)

            else:
                output += fmt_removed(key, previous[key]['description'])
                output += fmt_representations(key, previous[key]['representations'], fmt_removed_dynamic)

        return output

    def as_dict(self):
        def describe_field_type(field):
            field_type = field.get('func_name', '')
            child = field.get('child', '')

            if child:
                field_type = '{field_type}({child})'.format(
                    field_type=field_type,
                    child=child
                )

            return '[{}]'.format(field_type) if field_type else ''

        def field_description(field):
            checked_properties = ['required', 'read_only']
            properties = [prop
                          for prop in checked_properties
                          if field[prop]]
            field_type_desc = describe_field_type(field)
            properties_desc = ', '.join(properties)
            return ' '.join([field_type_desc, properties_desc]).strip()

        def field_representations(field):
            return dict(
                (condition, field_description(representation))
                for condition, representation
                in field.get('representations', {}).iteritems()
                )

        def describe_field(field):
            key = field['field_name']
            value = {
                'description': field_description(field),
                'representations': field_representations(field)
            }

            return key, value

        return dict(
            describe_field(field)
            for field in self.values()
        )
