from libcst.codemod import CodemodContext, CodemodTest
from libcst.metadata import FullRepoManager, FullyQualifiedNameProvider, ScopeProvider

from bump_pydantic.codemods import OrmarCodemod
from bump_pydantic.codemods.class_def_visitor import OrmarClassDefVisitor, OrmarMetaClassDefVisitor
from bump_pydantic.codemods.ormar import OrmarCodemod


class TestOrmarCodemod(CodemodTest):
    TRANSFORM = OrmarCodemod

    maxDiff = None

    def setUp(self) -> None:
        scratch = {}
        providers = {FullyQualifiedNameProvider, ScopeProvider}
        metadata_manager = FullRepoManager(".", ["foo.py"], providers=providers)  # type: ignore[arg-type]
        metadata_manager.resolve_cache()
        context = CodemodContext(
            metadata_manager=metadata_manager,
            filename="foo.py",
            # full_module_name=module_and_package.name,
            # full_package_name=module_and_package.package,
            scratch=scratch,
        )

        scratch[OrmarClassDefVisitor.BASE_MODEL_CONTEXT_KEY] = {"ormar.Model", "foo.Album"}
        scratch[OrmarMetaClassDefVisitor.BASE_MODEL_CONTEXT_KEY] = {"ormar.ModelMeta", "foo.BaseMeta"}
        self.context = context
        return super().setUp()

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
        self.assertCodemod(before, after, context_override=self.context)


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
        self.assertCodemod(before, after, context_override=self.context)
