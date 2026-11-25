# -*- coding: utf-8 -*-
"""Validate duplication suffixes of loaded template nodes."""
import collections

import pyblish.api

import ayon_harmony.api as harmony
from ayon_core.pipeline import OptionalPyblishPluginMixin
from ayon_core.pipeline.publish import (
    ValidateContentsOrder,
    PublishXmlValidationError,
    RepairContextAction,
)


class ValidateTemplateDuplication(
    pyblish.api.ContextPlugin,
    OptionalPyblishPluginMixin,
):
    """Validate loaded template top node suffixes match duplication count.

    Loaded templates sharing the same representation are copies of each other,
    so their top nodes must be suffixed from 0 to ``count - 1``, the first
    copy being suffixless.
    """

    label = "Validate Template Duplication"
    hosts = ["harmony"]
    order = ValidateContentsOrder
    settings_category = "harmony"
    actions = [RepairContextAction]
    optional = True
    active = True

    @staticmethod
    def _iter_groups():
        """Yield ``(count, paths)`` for each group of identical templates.

        Templates are grouped by representation id. ``paths`` is the flat list
        of top node paths of every container in the group.
        """
        containers = [
            container for container in harmony.ls()
            if container.get("loader") == "TemplateLoader"
        ]
        groups = collections.defaultdict(list)
        for container in containers:
            groups[container["representation"]].append(container)

        for group in groups.values():
            paths = []
            for container in group:
                paths.extend(
                    harmony.get_backdrop_top_nodes(container["name"])
                )
            yield len(group), paths

    def process(self, context: pyblish.api.Context) -> None:
        """Plugin entry point."""
        if not self.is_active(context.data):
            return

        invalid_lines = []
        for count, paths in self._iter_groups():
            suffixes_by_base = collections.defaultdict(set)
            for path in paths:
                base, suffix = harmony.parse_node_suffix(
                    path.rsplit("/", 1)[-1]
                )
                suffixes_by_base[base].add(suffix)
            for base, suffixes in suffixes_by_base.items():
                unique = sorted(suffixes)
                if (
                    unique[-1] >= count
                    or unique != list(range(len(unique)))
                ):
                    invalid_lines.append(
                        f"{base}: found suffixes {unique} for {count} "
                        f"loaded copies (expected 0..{count - 1})"
                    )

        if invalid_lines:
            msg = "Template node suffixes do not match loaded copies:\n{}"
            raise PublishXmlValidationError(
                self,
                msg.format("\n".join(invalid_lines)),
                formatting_data={"invalid_nodes": "<br/>".join(invalid_lines)},
            )

    @classmethod
    def repair(cls, context: pyblish.api.Context) -> None:
        """Renumber top nodes contiguously and remove surplus copies."""
        for count, paths in cls._iter_groups():
            paths_by_base = collections.defaultdict(list)
            for path in paths:
                base, suffix = harmony.parse_node_suffix(
                    path.rsplit("/", 1)[-1]
                )
                paths_by_base[base].append((suffix, path))

            for base, entries in paths_by_base.items():
                entries.sort(key=lambda entry: entry[0])
                for _, path in entries[count:]:
                    harmony.delete_node(path)
                for index, (_, path) in enumerate(entries[:count]):
                    name = path.rsplit("/", 1)[-1]
                    new_name = base if index == 0 else f"{base}_{index}"
                    if new_name != name:
                        harmony.rename_node(name, new_name)
