import ast
import os

from collections import defaultdict

from termcolor import colored
from tabulate import tabulate

import consts

from resolver import Resolver
from fields import Fields


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


class DynamicFieldsVisitor(ast.NodeVisitor):
    def visit_Assign(self, node):
        pass


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

                    lhs, rhs = Resolver.resolve(node)
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
        try:
            return Resolver.resolve(node)
        except AttributeError:
            raise

    def augment_field(self, previous, current):
        previous.update_representations(current.get('representations', {}))

        return previous

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
                fields.add(Resolver.drf_field_assignment(node), overwrite=True)
            elif self.is_meta(node):
                fields.extend(Resolver.drf_meta_fields(node))
            elif self.is_init_method(node):
                init_node = node

        # add fields from bases, in left to right order. The bases of the base
        # trumps the neighbour of the base if there's overlap.
        for base in class_node.bases:
            base = Resolver.resolve(base)

            if base == 'object':
                continue

            if base not in nodes:
                # TODO: ???
                continue

            base_class_vars = self.find_serializer_fields(base)
            fields.extend(base_class_vars)

        # dynamic fields trump or augment existing fields
        if serializer_name in self.dynamic_fields:
            if not init_node:
                msg = ('Did not find __init__ in {} but view specifies dynamic'
                       ' fields.').format(serializer_name)
                raise Exception(msg)

            dynamic_fields = Resolver.init_method(init_node)
            for field_name, field in dynamic_fields.iteritems():
                if field_name not in fields:
                    fields.add(field)
                    continue

                previous_field = fields[field_name]
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


def fmt_serializer(node, fields):
    output = ('{}({})\n'
              '{}\n')
    table_data = tabulate(fields, headers="keys", tablefmt='grid')

    return output.format(
        node.name,
        ', '.join(Resolver.resolve(base) for base in node.bases),
        table_data
    )
