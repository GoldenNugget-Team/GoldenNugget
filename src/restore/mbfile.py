"""Validated MBFile keyed archives, preserving unknown device metadata."""
import plistlib
from copy import deepcopy
from dataclasses import dataclass


class InvalidMBFile(ValueError):
    pass


@dataclass
class MBFileArchive:
    archive: dict
    root_index: int

    @classmethod
    def decode(cls, payload):
        try:
            archive = plistlib.loads(payload)
            objects = archive["$objects"]
            root = archive.get("$top", {}).get("root", 1)
            index = root.data if isinstance(root, plistlib.UID) else root
            if (type(index) is not int or not isinstance(objects, list)
                    or not 0 <= index < len(objects) or not isinstance(objects[index], dict)):
                raise ValueError("Invalid MBFile root")
            return cls(archive, index)
        except Exception as exc:
            raise InvalidMBFile(f"Invalid MBFile metadata: {exc}") from exc

    @property
    def fields(self):
        return self.archive["$objects"][self.root_index]

    def clone(self):
        return MBFileArchive(deepcopy(self.archive), self.root_index)

    def set_reference(self, field, value):
        objects = self.archive["$objects"]
        reference = self.fields.get(field)
        index = reference.data if isinstance(reference, plistlib.UID) else reference
        if type(index) is int and 0 < index < len(objects) and index != self.root_index:
            objects[index] = value
        else:
            self.fields[field] = plistlib.UID(len(objects))
            objects.append(value)

    def encode(self):
        return plistlib.dumps(self.archive, fmt=plistlib.FMT_BINARY)
