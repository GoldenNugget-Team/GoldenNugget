from src.controllers.archive_safety import package_matches
from . import TemplateOption

from typing import Any, Optional
from enum import Enum

from src.utils.color import RgbColor
from src.controllers.xml_handler import set_xml_value, set_xml_values
from src.controllers.plist_handler import write_plist_value


class SetterType(Enum):
    textbox = "textbox"
    slider = "slider"
    toggle = "toggle"
    color_picker = "color_picker"


class SetOption(TemplateOption):
    identifier: str  # nuggetId for properties in caml
    key: str  # key of the property to change
    setter_type: SetterType  # the type of input the user sees for setting the value
    use_ca_id: bool = False  # whether or not to use the ca id over nuggetId

    # slider options
    min_value: Optional[int] = None  # minimum value allowed for input
    max_value: Optional[int] = None  # maximum value allowed for input
    step: int = 1  # the interval between each slider value
    value_type = int  # value types

    # toggle options
    inverted: bool = False  # if set to true, the bool value will be inverted
    toggle_off_value: Optional[Any] = None  # the value to set when the toggle is off (for non-boolean values)
    toggle_on_value: Optional[Any] = None  # the value to set when the toggle is on (for non-boolean values)

    # color picker options
    sets_opacity: bool = False  # whether or not the color_picker sets the opacity value

    value: Any = 0  # whether or not to delete the file
    value_tag: Optional[str] = None  # the value tag in the caml (ie "scale(0 0 0)")

    def split_value(self, value):
        if value == None:
            return None
        if isinstance(value, str) and ' ' in value:
            # first get the value tag
            rm = value
            if '(' in value and ')' in value:
                rm = value.split('(')
                self.value_tag = rm[0]
                rm = rm[1].removesuffix(')')
            # split into values
            spl = rm.split(' ')
            parsed_spl = list(map(self.convert_str, spl))
            # convert to color
            if self.setter_type == SetterType.color_picker:
                # get optional alpha
                alpha: int = 255
                if len(parsed_spl) >= 4:
                    self.sets_opacity = True
                    alpha = self.convert_color(parsed_spl[3])
                color = RgbColor(
                    self.convert_color(parsed_spl[0]),
                    self.convert_color(parsed_spl[1]),
                    self.convert_color(parsed_spl[2]),
                    alpha,
                )
                return color
            return parsed_spl
        return value

    def __init__(self, data: dict):
        super().__init__(data=data)
        self.identifier = data['identifier']
        self.key = data['key']
        self.setter_type = SetterType[data['setter_type']]
        if 'use_ca_id' in data:
            self.use_ca_id = data['use_ca_id']

        if 'value_type' in data:
            self.value_type = data['value_type']

        # slider options
        if self.setter_type == SetterType.slider:
            # min and max values required
            self.min_value = data['min_value']
            self.max_value = data['max_value']
        elif self.setter_type == SetterType.textbox:
            # optional min and max values
            if 'min_value' in data:
                self.min_value = data['min_value']
            if 'max_value' in data:
                self.max_value = data['max_value']
        if 'step' in data:
            self.step = data['step']

        # toggle options
        if 'inverted' in data:
            self.inverted = data['inverted']
        if 'toggle_off_value' in data:
            self.toggle_off_value = data['toggle_off_value']
        if 'toggle_on_value' in data:
            self.toggle_on_value = data['toggle_on_value']

        # color picker options
        if 'sets_opacity' in data:
            self.sets_opacity = data['sets_opacity']

        if 'default_value' in data:
            self.value = data['default_value']
        else:
            if self.setter_type == SetterType.toggle:
                self.value = False
            elif self.min_value != None:
                self.value = self.min_value
            elif self.max_value != None:
                self.value = self.max_value

        # convert values
        self.min_value = self.split_value(self.min_value)
        self.max_value = self.split_value(self.max_value)
        self.step = self.split_value(self.step)
        self.value = self.split_value(self.value)

    # correcting the slider position
    def correct_slider_pos(self, pos: int, index: int = 0):
        # check if slider is divisible. If not, set it to a divisible value
        step = self.convert_float(self.step)
        if isinstance(step, list):
            step = step[index]
        if pos % step != 0:
            # pos needs updated
            min_val = self.convert_float(self.min_value)
            max_val = self.convert_float(self.max_value)
            if isinstance(min_val, list):
                min_val = min_val[index]
                max_val = max_val[index]
            if pos % step < step / 2:
                # set to left
                pos = pos - (pos % step)
            else:
                # set to right
                pos = pos + (step - (pos % step))
            # make sure it is within bounds
            if pos < min_val:
                pos = min_val
            elif pos > max_val:
                pos = max_val
        return pos

    # Converter functions
    def convert_float(self, value: float) -> int:
        if self.value_type != "float":
            return value
        if isinstance(value, list):
            return [self.convert_float(item) for item in value]
        return int(value * 1000)

    def convert_str(self, value: str):
        # convert string to either float or int
        if self.value_type == "float":
            return float(value)
        if isinstance(value, int) or (isinstance(value, str) and value.isdigit() and not '.' in value):
            return int(value)
        else:
            if self.setter_type == SetterType.slider:
                self.value_type = "float"
            return float(value)

    def convert_color(self, value: float):
        return round(min(1, value) * 255)

    def convert_back(self, value):
        back_list = value
        if isinstance(value, RgbColor):
            # convert color back to string
            back_list = [str(value.redF()), str(value.greenF()), str(value.blueF())]
        elif not isinstance(value, list):
            return value
        elif isinstance(value, list):
            # convert values to strings
            back_list = [str(item) for item in value]
        back_str = ' '.join(back_list)
        if self.value_tag != None:
            back_str = self.value_tag + "(" + back_str + ")"
        return back_str

    def update_value(self, nv: int, index: int = None):
        if self.setter_type == SetterType.slider:
            # correct it to the step
            nv = self.correct_slider_pos(nv, index)
            if self.value_type == "float":
                nv = float(nv) / 1000.0
        if isinstance(self.value, list):
            self.value[index] = nv
        else:
            self.value = nv

    def update_bool(self, nv: bool):
        self.value = nv

    def update_color(self, color: RgbColor):
        self.value = color

    def apply(self, container_path: str):
        apply_val = self.value
        if self.setter_type == SetterType.toggle:
            if self.inverted:
                # invert toggle
                apply_val = not apply_val
            if apply_val and self.toggle_on_value != None:
                apply_val = self.toggle_on_value
            elif not apply_val and self.toggle_off_value != None:
                apply_val = self.toggle_off_value
        # wildcard support
        for file in self.files:
            for full_path in package_matches(container_path, file):
                # handle for file types
                if full_path.endswith(".caml") or full_path.endswith(".xml"):
                    # set opacity if it has that
                    if self.sets_opacity and isinstance(self.value, RgbColor):
                        set_xml_values(file=full_path, id=self.identifier, keys=[self.key, "opacity"], values=[self.convert_back(apply_val), str(self.value.alphaF())], use_ca_id=self.use_ca_id)
                    else:
                        set_xml_value(file=full_path, id=self.identifier, key=self.key, val=self.convert_back(apply_val), use_ca_id=self.use_ca_id)
                elif full_path.endswith(".plist"):
                    # Plist editing
                    write_plist_value(full_path, self.key, apply_val)
                else:
                    # plain text editing
                    with open(full_path, "r") as in_file:
                        contents = in_file.read()
                    # replace occurrences and overwrite
                    contents = contents.replace(self.key, str(apply_val))
                    with open(full_path, "w") as out_file:
                        out_file.write(contents)
