from typing import Any

from libcst import MetadataWrapper, parse_module
from libcst.codemod import CodemodContext, CodemodTest
from libcst.metadata import FullRepoManager

from bump_pydantic.codemods import OrmarCodemod
from bump_pydantic.codemods.class_def_visitor import ClassDefVisitor
from bump_pydantic.codemods.ormar import OrmarCodemod

DEFAULT_PATH = "foo.py"

class TestOrmarCodemod(CodemodTest):
    TRANSFORM = OrmarCodemod

    maxDiff = None

    def setUp(self) -> None:
        scratch = {}
        providers = [*self.TRANSFORM.METADATA_DEPENDENCIES, *ClassDefVisitor.METADATA_DEPENDENCIES]
        metadata_manager = FullRepoManager(".", [DEFAULT_PATH], providers=providers)  # type: ignore[arg-type]
        metadata_manager.resolve_cache()
        context = CodemodContext(
            metadata_manager=metadata_manager,
            filename=DEFAULT_PATH,
            # full_module_name=module_and_package.name,
            # full_package_name=module_and_package.package,
            scratch=scratch,
        )

        self.context = context
        return super().setUp()

    def assertCodemod(
        self,
        before: str,
        after: str,
        *args: Any,
        **kwargs: Any) -> None:
        mod = MetadataWrapper(
            parse_module(CodemodTest.make_fixture_data(before)), True,
            cache=self.context.metadata_manager.get_cache_for_path(DEFAULT_PATH),
        )
        instance = ClassDefVisitor(context=self.context)
        mod.visit(instance)
        super().assertCodemod(before, after, *args, context_override=self.context, **kwargs)

    def test_replace_meta(self) -> None:
        before = """
        import databases
        import ormar
        import sqlalchemy

        database = databases.Database("sqlite:///db.sqlite")
        metadata = sqlalchemy.MetaData()

        class Album(ormar.Model):
            class Meta:
                database = database
                metadata = metadata
                tablename = "albums"

            id: int = ormar.Integer(primary_key=True)
            name: str = ormar.String(max_length=100)
            favorite: bool = ormar.Boolean(default=False)
        """
        after = """
        import databases
        import ormar
        import sqlalchemy

        database = databases.Database("sqlite:///db.sqlite")
        metadata = sqlalchemy.MetaData()

        class Album(ormar.Model):
            ormar_config = ormar.OrmarConfig(
                database=database,
                metadata=metadata,
                tablename="albums",
            )

            id: int = ormar.Integer(primary_key=True)
            name: str = ormar.String(max_length=100)
            favorite: bool = ormar.Boolean(default=False)
        """
        self.assertCodemod(before, after)


    def test_replace_base_meta(self) -> None:
        before = """
        import databases
        import ormar
        import sqlalchemy

        class BaseMeta(ormar.ModelMeta):
            database = databases.Database("sqlite:///db.sqlite")
            metadata = sqlalchemy.MetaData()

        class Album(ormar.Model):
            class Meta(BaseMeta):
                tablename = "albums"

            id: int = ormar.Integer(primary_key=True)
            name: str = ormar.String(max_length=100)
            favorite: bool = ormar.Boolean(default=False)
        """
        after = """
        import databases
        import ormar
        import sqlalchemy

        base_ormar_config = ormar.OrmarConfig(
            database=databases.Database("sqlite:///db.sqlite"),
            metadata=sqlalchemy.MetaData(),
        )

        class Album(ormar.Model):
            ormar_config = base_ormar_config.copy(
                tablename="albums",
            )

            id: int = ormar.Integer(primary_key=True)
            name: str = ormar.String(max_length=100)
            favorite: bool = ormar.Boolean(default=False)
        """
        self.assertCodemod(before, after)


    def test_replace_base_meta_import(self) -> None:
        before = """
        import databases
        import ormar
        import sqlalchemy
        from mybase import BaseMeta

        class Album(ormar.Model):
            class Meta(BaseMeta):
                tablename = "albums"

            id: int = ormar.Integer(primary_key=True)
            name: str = ormar.String(max_length=100)
            favorite: bool = ormar.Boolean(default=False)
        """
        after = """
        import databases
        import ormar
        import sqlalchemy
        from mybase import base_ormar_config

        class Album(ormar.Model):
            ormar_config = base_ormar_config.copy(
                tablename="albums",
            )

            id: int = ormar.Integer(primary_key=True)
            name: str = ormar.String(max_length=100)
            favorite: bool = ormar.Boolean(default=False)
        """
        self.assertCodemod(before, after)


    def test_replace_base_meta_docstring(self) -> None:
        before = """
        import databases
        import ormar
        import sqlalchemy

        class BaseMeta(ormar.ModelMeta):
            '''My custom base meta class.'''
            database = databases.Database("sqlite:///db.sqlite")
            metadata = sqlalchemy.MetaData()

        class Album(ormar.Model):
            class Meta(BaseMeta):
                tablename = "albums"

            id: int = ormar.Integer(primary_key=True)
            name: str = ormar.String(max_length=100)
            favorite: bool = ormar.Boolean(default=False)
        """
        after = """
        import databases
        import ormar
        import sqlalchemy

        base_ormar_config = ormar.OrmarConfig(
            database=databases.Database("sqlite:///db.sqlite"),
            metadata=sqlalchemy.MetaData(),
        )

        class Album(ormar.Model):
            ormar_config = base_ormar_config.copy(
                tablename="albums",
            )

            id: int = ormar.Integer(primary_key=True)
            name: str = ormar.String(max_length=100)
            favorite: bool = ormar.Boolean(default=False)
        """
        self.assertCodemod(before, after)


    def test_replace_base_meta_multiword(self) -> None:
        before = """
        import databases
        import ormar
        import sqlalchemy

        class MyBaseMeta(ormar.ModelMeta):
            database = databases.Database("sqlite:///db.sqlite")
            metadata = sqlalchemy.MetaData()

        class Album(ormar.Model):
            class Meta(MyBaseMeta):
                tablename = "albums"

            id: int = ormar.Integer(primary_key=True)
            name: str = ormar.String(max_length=100)
            favorite: bool = ormar.Boolean(default=False)
        """
        after = """
        import databases
        import ormar
        import sqlalchemy

        my_base_ormar_config = ormar.OrmarConfig(
            database=databases.Database("sqlite:///db.sqlite"),
            metadata=sqlalchemy.MetaData(),
        )

        class Album(ormar.Model):
            ormar_config = my_base_ormar_config.copy(
                tablename="albums",
            )

            id: int = ormar.Integer(primary_key=True)
            name: str = ormar.String(max_length=100)
            favorite: bool = ormar.Boolean(default=False)
        """
        self.assertCodemod(before, after)
