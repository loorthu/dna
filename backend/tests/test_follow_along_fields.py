"""Tests for the external review id and project code exposed for Follow Along."""

import os
from unittest import mock

import pytest

from dna.models.entity import Project, Version
from dna.prodtrack_providers.shotgrid import (
    FIELD_MAPPING,
    ShotgridProvider,
    _version_fields_with_external_ref,
)

BASE_VERSION_FIELDS = {
    "id": "id",
    "code": "name",
    "sg_status_list": "status",
}


class TestVersionExternalRefFieldMapping:
    """The external ref field is opt-in, because it is site-specific."""

    def test_unset_leaves_the_query_field_list_unchanged(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            assert (
                _version_fields_with_external_ref(BASE_VERSION_FIELDS)
                == BASE_VERSION_FIELDS
            )

    def test_blank_is_treated_as_unset(self):
        with mock.patch.dict(
            os.environ, {"PRODTRACK_VERSION_EXTERNAL_REF_FIELD": "   "}
        ):
            assert (
                _version_fields_with_external_ref(BASE_VERSION_FIELDS)
                == BASE_VERSION_FIELDS
            )

    def test_configured_field_is_added(self):
        with mock.patch.dict(
            os.environ, {"PRODTRACK_VERSION_EXTERNAL_REF_FIELD": "sg_jts"}
        ):
            fields = _version_fields_with_external_ref(BASE_VERSION_FIELDS)

        assert fields["sg_jts"] == "external_ref"
        assert fields["code"] == "name"

    def test_the_input_mapping_is_not_mutated(self):
        original = dict(BASE_VERSION_FIELDS)
        with mock.patch.dict(
            os.environ, {"PRODTRACK_VERSION_EXTERNAL_REF_FIELD": "sg_jts"}
        ):
            _version_fields_with_external_ref(BASE_VERSION_FIELDS)

        assert BASE_VERSION_FIELDS == original

    def test_no_external_ref_is_requested_by_default(self):
        """Guard for sites with no such field: the query must not ask for one.

        Asserted against the SHIPPED version field list with any configured entry stripped,
        rather than against the imported constant as-is. FIELD_MAPPING is built from the
        environment at import, so a machine that configures the field — as SPI's dev stack
        does — legitimately has one in there; reading the constant directly asserted only how
        the test runner happened to be configured, and failed for that reason alone.
        """
        base = {
            key: value
            for key, value in FIELD_MAPPING["version"]["fields"].items()
            if value != "external_ref"
        }

        with mock.patch.dict(os.environ, {}, clear=True):
            assert _version_fields_with_external_ref(base) == base


class TestProjectCodeFieldMapping:
    def test_project_code_maps_from_tank_name(self):
        assert FIELD_MAPPING["project"]["fields"]["tank_name"] == "code"

    def test_project_query_asks_for_every_mapped_field(self):
        """get_projects_for_user hardcodes its field list; keep it in step."""
        with (
            mock.patch("dna.prodtrack_providers.shotgrid.Shotgun") as mock_sg,
            mock.patch.dict(
                os.environ,
                {
                    "SHOTGRID_URL": "https://test.shotgunstudio.com",
                    "SHOTGRID_SCRIPT_NAME": "test_script",
                    "SHOTGRID_API_KEY": "test_key",
                },
            ),
        ):
            provider = ShotgridProvider(connect=True)
            mock_sg.return_value.find.return_value = []
            provider.get_projects_for_user("someone@example.com")

        requested = mock_sg.return_value.find.call_args.kwargs["fields"]
        assert set(requested) == set(FIELD_MAPPING["project"]["fields"].keys())


class TestModelConversion:
    def test_version_keeps_the_external_ref_as_a_string(self):
        assert Version(id=1, external_ref=4815162342).external_ref == "4815162342"

    def test_version_preserves_a_string_external_ref_verbatim(self):
        assert Version(id=1, external_ref="007").external_ref == "007"

    def test_version_external_ref_defaults_to_none(self):
        assert Version(id=1).external_ref is None

    def test_project_carries_a_code(self):
        assert Project(id=1, name="Night Show", code="nite").code == "nite"

    def test_project_code_defaults_to_none(self):
        assert Project(id=1, name="Night Show").code is None


@pytest.mark.parametrize("sg_value", [42, "42", " 42 "])
def test_shotgrid_values_of_any_type_land_as_strings(sg_value):
    assert isinstance(Version(id=1, external_ref=sg_value).external_ref, str)
