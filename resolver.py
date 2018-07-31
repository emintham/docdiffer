import ast

from fields import Field, Fields


class Resolver(object):
    """
    Wrapper class for static methods to resolve various ast nodes and more
    complex datatypes to their respective data.
    """

    @staticmethod
    def resolve(node):
        node_type = type(node).__name__.split('.')[-1]
        method = getattr(Resolver, node_type)
        return method(node)

    @staticmethod
    def Call(field_node):
        try:
            func = field_node.func
        except AttributeError:
            print field_node

        # e.g. serializers.CharField
        if isinstance(func, ast.Attribute):
            # Attribute has value: Name
            #               attr : str
            return Resolver.Attribute(func)
        else:
            return func.id

    @staticmethod
    def Attribute(node):
        rhs = node.attr
        lhs = Resolver.resolve(node.value)

        return '.'.join([lhs, rhs])

    @staticmethod
    def Assign(node):
        # TODO: We don't usually do multi assignments
        target = node.targets[0]

        if hasattr(target, 'id'):
            lhs = target.id
        else:
            # This is a Subscript node and should probably be represented
            # in a better way to demonstrate that.
            lhs = Resolver.resolve(target.slice)

        rhs = node.value

        return (lhs, rhs)

    @staticmethod
    def Name(node):
        return node.id

    @staticmethod
    def Str(node):
        return node.s

    @staticmethod
    def Num(node):
        return node.n

    @staticmethod
    def List(node):
        return [Resolver.resolve(x) for x in node.elts]

    @staticmethod
    def Index(node):
        return Resolver.resolve(node.value)

    @staticmethod
    def Tuple(node):
        return tuple(Resolver.resolve(x) for x in node.elts)

    @staticmethod
    def keywords(keywords):
        # each keyword is a `keyword` with arg: str and value: node
        return {
            keyword.arg: Resolver.resolve(keyword.value)
            for keyword in keywords
        }

    @staticmethod
    def func_params(field_node):
        field = Field()

        if field_node.args:
            field['args'] = Resolver.resolve(field_node.args)

        field.update(**Resolver.keywords(field_node.keywords))

        return field

    @staticmethod
    def drf_field_assignment(node):
        field_name, rhs = Resolver.resolve(node)

        # TODO: we don't care about other class variables.
        if not isinstance(rhs, ast.Call):
            return None

        return Resolver.parse_drf_field_node(field_name, rhs)

    @staticmethod
    def drf_meta_fields(meta_node):
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
                    field = Field(field_name=Resolver.resolve(field_node),
                                  read_only=read_only)

                    fields.append(field)

            return fields

        fields = Fields()

        for node in meta_node.body:
            if not isinstance(node, ast.Assign):
                continue

            lhs, rhs = Resolver.resolve(node)

            if lhs == 'fields':
                fields.extend(resolve_fields(rhs))
            elif lhs == 'read_only_fields':
                fields.extend(resolve_fields(rhs, read_only=True))

        return fields

    @staticmethod
    def parse_drf_field_node(field_name, field_node):
        return Field(field_name=field_name,
                     func_name=Resolver.resolve(field_node),
                     **Resolver.func_params(field_node))

    @staticmethod
    def is_filter_conditional(node):
        return (
            isinstance(node, ast.If) and
            # TODO: Might need to support more test types. This isn't flexible.
            # Currently it only returns true when testing a variable name or
            # an unary operation like `if some_var` or `if not some_var`.
            (isinstance(node.test, ast.Name) or isinstance(node.test, ast.UnaryOp))
        )
    @staticmethod
    def is_assignment_to_field(node):
        return (
            isinstance(node, ast.Assign) and
            isinstance(node.targets[0], ast.Subscript) and
            isinstance(node.targets[0].value, ast.Attribute) and
            node.targets[0].value.attr == 'fields'
        )

    @staticmethod
    def init_method(init_node):
        fields = Fields()

        # TODO: This method currently only detects field assignments
        # It needs to also support field deletions eventually.
        for init_body_node in init_node.body:

            if not Resolver.is_filter_conditional(init_body_node):
                continue

            for if_body_node in init_body_node.body:

                if not Resolver.is_assignment_to_field(if_body_node):
                    continue

                filter_name = Resolver.resolve(init_body_node.test)
                field = Resolver.drf_field_assignment(if_body_node)

                # TODO: Sometimes fields are assigned to temporary variables
                # before being assigned to the actual field.
                if not field:
                    continue

                fields.add_representation(field['field_name'], filter_name, field)

        return fields
