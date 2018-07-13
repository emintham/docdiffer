import ast
import os

from collections import defaultdict

from termcolor import colored
from tabulate import tabulate

import consts


def parse_module(filename):
    with open(filename, 'rb') as f:
        module = f.read()

    try:
        return filename, ast.parse(module)
    except TypeError:
        raise TypeError('Bad file {}'.format(filename))


def parse_directory(location):
    for filename in walk(location):
        yield parse_module(filename)


def walk(location):
    for dirpath, dirs, files in os.walk(location):
        for f in files:
            filename, ext = os.path.splitext(f)
            if ext == '.py':
                yield os.path.join(dirpath, f)


class ClassVisitor(ast.NodeVisitor):
    """
    Registers top-level class definitions into a ClassRegistry.
    """

    def __init__(self, filename=None, classes=None, *args, **kwargs):
        self.classes = classes
        self.filename = filename
        super(ClassVisitor, self).__init__(*args, **kwargs)

    def visit_ClassDef(self, node):
        self.classes.add(node, self.filename)
        self.generic_visit(node)


class ClassDiff(object):
    def __init__(self, added=None, removed=None):
        self.added = added or []
        self.removed = removed or []

    def __contains__(self, thing):
        return thing in self.added or thing in self.removed

    # python 2 compat
    def __nonzero__(self):
        return bool(self.added + self.removed)

    def __bool__(self):
        return self.__nonzero__()


class ClassRegistry(object):
    """
    Data store for classes.

    ClassRegistry.nodes
    - what is the node of this class?
    - class_name:str -> class_node: ast.ClassDef

    ClassRegistry.classes
    - which classes are defined in this file?
    - filename:str -> classes: [str]

    ClassRegistry.class_source
    - which files defined this class
    - class_name:str -> filenames: [str]
    """

    IGNORED_CLASSES = (
        'Meta',
        'Messages',
    )

    def __init__(self):
        self.nodes = {}
        self.classes = defaultdict(list)
        self.class_source = defaultdict(list)

    def add(self, node, filename):
        node_name = node.name

        if node_name in self.IGNORED_CLASSES:
            return

        if node_name in self.nodes:
            # TODO: fix this case.. there are sometimes valid cases of
            # conflicting names
            msg = ('[WARNING] Re-definition of {} in {} that was previously '
                   'defined in {}\n').format(
                node_name,
                filename,
                ', '.join(self.class_source[node_name])
            )
            msg = colored(msg, consts.Colours.WARNING)
            print(msg)

        self.nodes[node_name] = node
        self.classes[filename].append(node_name)
        self.class_source[node_name].append(filename)

    def difference(self, other):
        """Diffs two registries with self being the base."""
        self_classes = set(self.nodes.keys())
        other_classes = set(other.nodes.keys())

        added = sorted(self_classes.difference(other_classes))
        removed = sorted(other_classes.difference(self_classes))

        return ClassDiff(added=added, removed=removed)

    def get_classes_in_file(self, filename):
        return self.classes[filename]


def resolve_args(args):
    if isinstance(args, ast.List):
        return [resolve_args(x) for x in args.elts]
    elif isinstance(args, ast.Str):
        return args.s


def resolve_Name(node):
    return node.id


def resolve_Str(node):
    return node.s


def resolve_Num(node):
    return node.n


def resolve_keywords(keywords):
    kwargs = {}

    # each keyword is a `keyword` with arg: str and value: node
    for keyword in keywords:
        value = keyword.value
        if isinstance(value, ast.Str):
            value = resolve_Str(value)
        elif isinstance(value, ast.Call):
            value = resolve_func_name(value)
        elif isinstance(value, ast.Name):
            value = resolve_Name(value)
        elif isinstance(value, ast.Num):
            value = resolve_Num(value)

        kwargs[keyword.arg] = value

    return kwargs


def resolve_func_params(field_node):
    kwargs = consts.DEFAULT_DRF_FIELD_KWARGS.copy()

    args = field_node.args
    if args:
        kwargs['args'] = resolve_args(args)

    kwargs.update(**resolve_keywords(field_node.keywords))

    return kwargs


def resolve_Attribute(node):
    lhs = node.value
    rhs = node.attr
    if isinstance(lhs, ast.Attribute):
        lhs = resolve_Attribute(lhs)
    elif isinstance(lhs, ast.Name):
        lhs = resolve_Name(lhs)

    return '.'.join([lhs, rhs])


def resolve_func_name(field_node):
    try:
        func = field_node.func
    except AttributeError:
        print field_node

    # e.g. serializers.CharField
    if isinstance(func, ast.Attribute):
        # Attribute has value: Name
        #               attr : str
        return resolve_Attribute(func)
    else:
        return func.id


def parse_drf_field_node(field_name, field_node):
    # field node is actually a Call node
    # TODO: refactor Field into a class
    func_props = {
        'field_name': field_name,
        'func_name': resolve_func_name(field_node)
    }
    func_props.update(**resolve_func_params(field_node))

    return func_props


def resolve_Assign(node):
    # We don't usually do multi assignments
    target = node.targets[0]
    lhs = target.id
    rhs = node.value

    return (lhs, rhs)


def resolve_class_var_drf_field(node):
    field_name, rhs = resolve_Assign(node)

    # XXX: we don't care about other class variables.
    if not isinstance(rhs, ast.Call):
        return None

    return parse_drf_field_node(field_name, rhs)


class Fields(dict):
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

    def find(self, field_name):
        return self[field_name]

    def stringify_diff(self, base):
        def fmt_added(key, val):
            return colored("+ '{}': {}\n".format(key, val), consts.Colours.ADDED)

        def fmt_removed(key, val):
            return colored("- '{}': {}\n".format(key, val), consts.Colours.REMOVED)

        current = self.as_dict()
        previous = base.as_dict()
        keys = set(current.keys()).union(previous.keys())

        output = ''
        for key in keys:
            if key in current and key in previous:
                if current[key] == previous[key]:
                    continue

                output += fmt_removed(key, previous[key])
                output += fmt_added(key, current[key])
            elif key in current:
                output += fmt_added(key, current[key])
            else:
                output += fmt_removed(key, previous[key])

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

        def describe_field(field):
            checked_properties = ['required', 'read_only']
            properties = [prop
                          for prop in checked_properties
                          if field[prop]]
            field_type_desc = describe_field_type(field)
            properties_desc = ', '.join(properties)
            description = ' '.join([field_type_desc, properties_desc]).strip()

            return field['field_name'], description

        return dict(
            describe_field(field)
            for field in self.values()
        )


def resolve_Meta_fields(meta_node):
    def resolve_fields(fields_node, read_only=False):
        fields = []
        known_types = [ast.Tuple, ast.List, ast.Set]

        if isinstance(fields_node, ast.BinOp):
            assert isinstance(fields_node.op, ast.Add)
            # if either is Attribute, resolve_fields returns [] which is fine
            # since it will be handled by the logic in bases
            return resolve_fields(fields_node.left) + resolve_fields(fields_node.right)

        if any(isinstance(fields_node, t) for t in known_types):
            for field_node in fields_node.elts:
                field = {'field_name': resolve_Str(field_node)}
                field.update(**consts.DEFAULT_DRF_FIELD_KWARGS)
                field['read_only'] = read_only

                fields.append(field)

        return fields

    fields = Fields()

    for node in meta_node.body:
        if not isinstance(node, ast.Assign):
            continue

        lhs, rhs = resolve_Assign(node)

        if lhs == 'fields':
            fields.extend(resolve_fields(rhs))
        elif lhs == 'read_only_fields':
            fields.extend(resolve_fields(rhs, read_only=True))

    return fields


class DynamicFieldsVisitor(ast.NodeVisitor):
    def visit_Assign(self, node):
        pass


def resolve_init_method(init_node):
    fields = Fields()
    return fields


class FieldFinder(object):
    def __init__(self, serializer_registry, view_registry):
        self.serializer_registry = serializer_registry
        self.view_registry = view_registry
        self._dynamic_field_map = {}
        self.memo_dict = {}

    @classmethod
    def is_init_method(cls, node):
        return isinstance(node, ast.FunctionDef) and node.name == '__init__'

    @classmethod
    def is_meta(cls, node):
        """True iff node is the DRF Meta nested class."""
        return isinstance(node, ast.ClassDef) and node.name == 'Meta'

    @classmethod
    def is_class_var(cls, node):
        return isinstance(node, ast.Assign)

    @property
    def dynamic_fields(self):
        if not self._dynamic_field_map:
            nodes = self.view_registry.nodes
            for class_name, class_node in nodes.iteritems():
                props = {
                    'include_filters': None,
                    'expand_filters': None,
                    'exclude_filters': None,
                    'serializer_class': None
                }

                for node in class_node.body:
                    if not self.is_class_var(node):
                        continue

                    lhs, rhs = resolve_Assign(node)
                    if lhs in props:
                        props[lhs] = self.resolve_view_var(rhs)

                serializer_name = props.pop('serializer_class')
                truncated_props = {
                    key: val
                    for key, val in props.iteritems()
                    if val
                }
                if truncated_props:
                    self._dynamic_field_map[serializer_name] = truncated_props

        return self._dynamic_field_map

    def resolve_view_var(self, node):
        if isinstance(node, ast.Tuple):
            return tuple(resolve_Str(n) for n in node.elts)
        elif isinstance(node, ast.Name):
            return resolve_Name(node)
        else:
            raise Exception

    def augment_field(self, previous, current):
        raise Exception

    def find_serializer_fields(self, serializer_name):
        nodes = self.serializer_registry.nodes

        if serializer_name in self.memo_dict:
            return self.memo_dict[serializer_name]

        class_node = nodes[serializer_name]
        fields = Fields()
        init_node = None

        # Look at own class variables first, this trumps everything else
        for node in class_node.body:
            if self.is_class_var(node):
                # explicit class var trumps Meta
                fields.add(resolve_class_var_drf_field(node), overwrite=True)
            elif self.is_meta(node):
                fields.extend(resolve_Meta_fields(node))
            elif self.is_init_method(node):
                init_node = node

        # add fields from bases, in left to right order. The bases of the base
        # trumps the neighbour of the base if there's overlap.
        for base in class_node.bases:
            base = resolve_base(base)

            if base == 'object':
                continue

            if base not in nodes:
                # print 'Base class `{}` not found!'.format(base)
                continue

            base_class_vars = self.find_serializer_fields(base)
            fields.extend(base_class_vars)

        # dynamic fields trump or augment existing fields
        if serializer_name in self.dynamic_fields:
            if not init_node:
                msg = ('Did not find __init__ in {} but view specifies dynamic '
                       'fields.').format(serializer_name)
                raise Exception(msg)

            dynamic_fields = resolve_init_method(node)
            for field in dynamic_fields:
                if field not in fields:
                    fields.add(field)
                    continue

                previous_field = fields[field['field_name']]
                augmented_field = self.augment_field(previous_field, field)
                fields.add(augmented_field, overwrite=True)

        self.memo_dict[serializer_name] = fields

        return fields

    def difference(self, other):
        return self.serializer_registry.difference(other.serializer_registry)

    @classmethod
    def crawl(cls, serializer_directory, view_directory, files=None):
        files = files or []

        serializer_registry = ClassRegistry()
        view_registry = ClassRegistry()

        for filename, tree in parse_directory(serializer_directory):
            ClassVisitor(filename=filename, classes=serializer_registry).visit(tree)

        for filename, tree in parse_directory(view_directory):
            ClassVisitor(filename=filename, classes=view_registry).visit(tree)

        for filename in files:
            filename, tree = parse_module(filename)
            ClassVisitor(filename=filename, classes=serializer_registry).visit(tree)

        return cls(serializer_registry, view_registry)


def resolve_base(node):
    if isinstance(node, ast.Name):
        return node.id
    elif isinstance(node, ast.Attribute):
        return resolve_Attribute(node)


def fmt_serializer(node, fields):
    output = ('{}({})\n'
              '{}\n')
    table_data = tabulate(fields, headers="keys", tablefmt='grid')

    return output.format(
        node.name,
        ', '.join(resolve_base(base) for base in node.bases),
        table_data
    )
