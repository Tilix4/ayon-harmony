# -*- coding: utf-8 -*-
"""Validate top node suffixes inside a single template."""
import collections

import pyblish.api

import ayon_harmony.api as harmony
from ayon_core.pipeline import OptionalPyblishPluginMixin
from ayon_core.pipeline.publish import (
    ValidateContentsOrder,
    PublishXmlValidationError,
    RepairAction,
)


class ValidateTemplateNodeSuffix(
    pyblish.api.InstancePlugin,
    OptionalPyblishPluginMixin,
):
    """Validate no template top node shares a base name with another suffix.

    A single template must not contain both ``head`` and ``head_1`` for
    instance, as all nodes of one loaded template carry the same suffix.
    """

    label = "Validate Template Node Suffix"
    hosts = ["harmony"]
    families = ["harmony.template"]
    order = ValidateContentsOrder
    settings_category = "harmony"
    actions = [RepairAction]
    optional = True
    active = True

    def process(self, instance: pyblish.api.Instance) -> None:
        """Plugin entry point."""
        if not self.is_active(instance.data):
            return

        backdrop = instance.data["setMembers"][0]
        suffixes_by_base = collections.defaultdict(set)
        for path in harmony.get_backdrop_top_nodes(backdrop):
            base, suffix = harmony.parse_node_suffix(path.rsplit("/", 1)[-1])
            suffixes_by_base[base].add(suffix)

        invalid_lines = [
            f"{base}: found suffixes {sorted(suffixes)}"
            for base, suffixes in suffixes_by_base.items()
            if len(suffixes) > 1
        ]
        if invalid_lines:
            msg = "Template nodes share a base name with other suffixes:\n{}"
            raise PublishXmlValidationError(
                self,
                msg.format("\n".join(invalid_lines)),
                formatting_data={"invalid_nodes": "<br/>".join(invalid_lines)},
            )

    @classmethod
    def repair(cls, instance: pyblish.api.Instance) -> None:
        """Keep the node matching the backdrop suffix, remove the others."""
        backdrop = instance.data["setMembers"][0]
        _, expected_suffix = harmony.parse_node_suffix(backdrop)

        paths_by_base = collections.defaultdict(list)
        for path in harmony.get_backdrop_top_nodes(backdrop):
            base, suffix = harmony.parse_node_suffix(path.rsplit("/", 1)[-1])
            paths_by_base[base].append((suffix, path))

        for entries in paths_by_base.values():
            if len({suffix for suffix, _ in entries}) <= 1:
                continue
            entries.sort(key=lambda entry: entry[0])
            kept = next(
                (
                    path for suffix, path in entries
                    if suffix == expected_suffix
                ),
                entries[0][1],
            )
            for _, path in entries:
                if path != kept:
                    harmony.delete_node(path)
