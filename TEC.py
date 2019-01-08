#!/usr/bin/env python3


import epics
import argparse
import shutil
import os
import sys
import fileinput
from threading import Thread
from time import sleep
from itertools import count
import urwid
from urwid import CURSOR_LEFT, CURSOR_RIGHT, CURSOR_UP, CURSOR_DOWN, REDRAW_SCREEN
import yaml
import subprocess

screen = None

parser = argparse.ArgumentParser()
parser.add_argument("-cf", "--config", help="YAML file with page configuration")
parser.add_argument(
    "-hf",
    "--header",
    help="YAML file with header configuration, usually for sonsitant headers",
)
parser.add_argument("-t", "--time", type=float, default=0.5, help="refresh time period")
parser.add_argument(
    "-m",
    "--macro",
    nargs="+",
    help='replace every "%M[x]" with this given value, list values in order, first value replaces %M1, second %M2, etc.',
)
parser.add_argument(
    "-v", "--verbose", help="increase output verbosity", action="store_true"
)

divider = urwid.Divider
text = urwid.Text
fill = urwid.SolidFill

try:
    TEC_path = os.environ["TEC_PATH"]
    bin_path = TEC_path + "/bin/"
    yaml_path = TEC_path + "/YAML/"
except KeyError:
    print(
        "(TEC_PATH) environement variable not defined, please define it in your .bashrc file or similar"
    )
    os._exit(1)


class Error(Exception):
    """Base class for exceptions in this module."""
    pass


class FieldParseError(Error):
    """Exception raised for errors in parsing a field in the YAML configuration file.

    Attributes:
        field -- input expression in which the error occurred
        message -- explanation of the error
    """

    def __init__(self, field, message):
        self.field = field
        self.message = "{} in field\n{}".format(message, field)


class editPV(urwid.Edit):

    """Container widget for writing to float output PVs"""
    count = 0

    def valid_char(self, ch):
        """
        Return true for decimal digits, decimal point and a negative sign.
        """
        return len(ch) == 1 and ch in "0123456789.-"

    def __init__(
        self, pv_name, enum=False, unit=None, align_t="left", display_precision=-1
    ):
        """
        Initializing editPV widget in 'disconnected' mode
        """
        self.pv_name = pv_name
        editPV.count += 1
        self.enum = enum
        if unit is None:
            self.unit = ""
        else:
            self.unit = unit
        self.enum_strs_len = 0
        self.enum_strs = []
        self.enum_strs_index = 0
        self.pv = epics.pv.PV(
            self.pv_name,
            auto_monitor=True,
            connection_timeout=0.0001,
            form=("ctrl" if self.enum else "native"),
        )
        self.conn = False

        if display_precision < 0:
            self.display_precision = self.pv.precision
        else:
            self.display_precision = display_precision
        self.__super.__init__(edit_text="Disconnected", wrap="clip", align=align_t)

    def keypress(self, size, key):
        """
        Handle editing keystrokes.  Remove leading zeros.
        >>> e, size = IntEdit(u"", 5002), (10,)
        >>> e.keypress(size, 'home')
        >>> e.keypress(size, 'delete')
        >>> print e.edit_text
        002
        >>> e.keypress(size, 'end')
        >>> print e.edit_text
        2
        """
        (maxcol,) = size
        if not self.enum:
            p = self.edit_pos

            if self._command_map[key] == CURSOR_LEFT:
                if p == 0:
                    return None
            elif self._command_map[key] == CURSOR_RIGHT:
                if p >= len(self.edit_text):
                    return None
            elif self._command_map[key] == CURSOR_UP:
                if (
                    p >= len(self.edit_text)
                    or self.edit_text[p] == "."
                    or self.edit_text[p] == "-"
                ):
                    return None
                point_pos = self.edit_text.find(".")
                if point_pos >= 0:
                    if point_pos < p:
                        super().set_edit_text(
                            "{:.{}f}{}".format(
                                float(self.edit_text.replace(self.unit, ""))
                                + (10 ** (-1 * (p - point_pos))),
                                self.display_precision,
                                self.unit,
                            )
                        )
                    else:
                        super().set_edit_text(
                            "{:.{}f}{}".format(
                                float(self.edit_text.replace(self.unit, ""))
                                + (10 ** (-1 * (p + 1 - point_pos))),
                                self.display_precision,
                                self.unit,
                            )
                        )
                else:
                    super().set_edit_text(
                        "{}{}".format(
                            int(self.edit_text.replace(self.unit, ""))
                            + (10 ** (len(self.edit_text) - p - 1)),
                            self.unit,
                        )
                    )
                self.write_value()
                return None
            elif self._command_map[key] == CURSOR_DOWN:
                if (
                    0
                    or p >= len(self.edit_text)
                    or self.edit_text[p] == "."
                    or self.edit_text[p] == "-"
                ):
                    return None
                point_pos = self.edit_text.find(".")
                if point_pos >= 0:
                    if point_pos < p:
                        super().set_edit_text(
                            "{:.{}f}{}".format(
                                float(self.edit_text.replace(self.unit, ""))
                                - (10 ** (-1 * (p - point_pos))),
                                self.display_precision,
                                self.unit,
                            )
                        )
                    else:
                        if self.edit_text[p] == 1:
                            next_non_zero_index = self.edit_text.match("[1-9]", p + 1)
                            super().set_edit_text(
                                "{:.{}f}{}".format(
                                    float(self.edit_text.replace(self.unit, ""))
                                    - (10 ** (-1 * (next_non_zero_index - point_pos))),
                                    self.display_precision,
                                    self.unit,
                                )
                            )
                        else:
                            super().set_edit_text(
                                "{:.{}f}{}".format(
                                    float(self.edit_text.replace(self.unit, ""))
                                    - (10 ** (-1 * (p + 1 - point_pos))),
                                    self.display_precision,
                                    self.unit,
                                )
                            )
                else:
                    super().set_edit_text(
                        "{}{}".format(
                            int(self.edit_text.replace(self.unit, ""))
                            - (10 ** (len(self.edit_text) - p - 1)),
                            self.unit,
                        )
                    )
                self.write_value()
                return None
            elif key == "." and key in self.edit_text:
                return None
            elif key == "-" and p != 0:
                return None
        else:
            """define what happens if enum mode here"""
            if self._command_map[key] == CURSOR_RIGHT:
                return None
            elif self._command_map[key] == CURSOR_LEFT:
                return None
            elif self._command_map[key] == CURSOR_UP:
                if self.enum_strs_index == self.enum_strs_len - 1:
                    return None
                else:
                    self.enum_strs_index = self.enum_strs_index + 1
                    super().set_edit_text(self.pv.enum_strs[self.enum_strs_index])
                return None
            elif self._command_map[key] == CURSOR_DOWN:
                if self.enum_strs_index == 0:
                    return None
                else:
                    self.enum_strs_index = self.enum_strs_index - 1
                    super().set_edit_text(self.pv.enum_strs[self.enum_strs_index])
                return None
            elif key == "p":
                super().set_edit_text(self.pv.enum_strs[self.pv.value])
                return None

        unhandled = super().keypress((maxcol,), key)

        return unhandled

    def write_value(self):
        """
        write the value to the PV
        """
        if self.enum:
            if self.edit_text in self.enum_strs:
                self.pv.put(self.enum_strs_index)
            else:
                self.enum_strs_index = self.pv.value
                super().set_edit_text(
                    u"{}".format(self.enum_strs[self.enum_strs_index])
                )
        else:
            if (
                self.edit_text == ""
                or self.edit_text == "-"
                or self.edit_text == "."
                or self.edit_text == "-."
            ):
                super().set_edit_text(
                    "{:.{}f}{}".format(self.pv.get(), self.display_precision, self.unit)
                )
            else:
                self.pv.put(float(self.edit_text.replace(self.unit, "")))

    def value(self):
        """
        Return the numeric value of self.edit_text.
        >>> e, size = IntEdit(), (10,)
        >>> e.keypress(size, '5')
        >>> e.keypress(size, '1')
        >>> e.value() == 51
        True
        """
        if self.edit_text:
            if self.enum:
                return self.edit_text
            else:
                return float(self.edit_text.replace(self.unit, ""))
        else:
            return 0


class setPV(urwid.AttrMap):
    """container widget to pass color when editing values"""
    count = 0

    def __init__(
        self, pv_name, enum=False, unit=None, display_precision=-1, scientific=False, align_text="left"
    ):
        """

        """
        self.pv_name = pv_name
        setPV.count += 1
        self.display_precision = display_precision
        self.enum = enum
        self.scientific = scientific
        if unit is not None:
            self.unit = unit
        else:
            self.unit = ""
        self.editing = False
        self.__super.__init__(
            editPV(
                self.pv_name,
                enum=enum,
                unit=unit,
                align_t=align_text,
                display_precision=self.display_precision,
            ),
            "disconnected",
            focus_map="disconnected",
        )
        self.original_widget.pv.connection_callbacks.append(self.on_connection_change)
        self.original_widget.pv.add_callback(callback=self.change_value)

        self.infoText = (
            "Widget type: {}\n"
            "PV Name:     {}\n"
            "Enum:        {}\n"
            "Precision:   {}\n"
            "Scientific:  {}\n"
            "Unit:        {}\n".format(
                self.__class__.__name__,
                self.pv_name,
                self.enum,
                self.display_precision,
                self.scientific,
                self.unit,
            )
        )

    def keypress(self, size, key):
        """
        Handle enter key to start editing the contents of the field, pass everything else to the parent
        """
        (maxcol,) = size

        if self.original_widget.conn:
            if key == "enter":
                if self.editing:
                    self.editing = False
                    point_pos = self.original_widget.edit_text.find(".")
                    if (
                        point_pos >= 0
                        and self.original_widget.edit_text != "."
                        and self.original_widget.edit_text != "-."
                    ):
                        self.original_widget.set_edit_text(
                            "{:.{}f}{}".format(
                                float(
                                    self.original_widget.edit_text.replace(
                                        self.unit, ""
                                    )
                                ),
                                self.original_widget.display_precision,
                                self.unit,
                            )
                        )
                    super().set_focus_map({None: "setPV_focus"})
                    self.original_widget.write_value()
                else:
                    self.editing = True
                    super().set_focus_map({None: "setPV_edit"})
                    self.original_widget.set_edit_pos(0)
                return None
        else:
            self.editing = False

        if self.editing:
            unhandled = self.original_widget.keypress((maxcol,), key)
        else:
            unhandled = key

        return unhandled

    def on_connection_change(self, conn, **kw):
        self.original_widget.conn = conn
        if conn:
            super().set_attr_map({None: "setPV"})
            super().set_focus_map({None: "setPV_focus"})

        else:
            self.editing = False
            super().set_attr_map({None: "disconnected"})
            super().set_focus_map({None: "disconnected"})
            self.original_widget.set_edit_text("Disconnected")

    def change_value(self, **kw):
        if not self.enum:
            self.original_widget.set_edit_text(
                u"{:.{}f}{}".format(
                    self.original_widget.pv.value, self.display_precision, self.unit
                )
            )
        else:
            # self.original_widget.set_edit_text(self.original_widget.pv.enum_strs[self.original_widget.pv.value])
            # map(lambda x : x*2, [1, 2, 3, 4])
            self.original_widget.enum_strs = list(
                map(lambda x: x.decode("utf-8"), self.original_widget.pv.enum_strs)
            )
            self.original_widget.enum_strs_len = len(self.original_widget.enum_strs)
            self.original_widget.enum_strs_index = int(self.original_widget.pv.value)
            if self.original_widget.enum_strs:
                self.original_widget.set_edit_text(
                    u"{}".format(
                        self.original_widget.enum_strs[
                            self.original_widget.enum_strs_index
                        ]
                    )
                )
            else:
                self.original_widget.set_edit_text("No enum")


class getPV(urwid.AttrMap):
    """Container widget for reading analog input PVs"""
    count = 0

    def __init__(
        self,
        pv_name,
        enum=False,
        display_precision=-1,
        scientific=False,
        unit=None,
        align_text="left",
        script=None,
    ):
        self.pv_name = pv_name
        getPV.count += 1
        if unit is not None:
            self.unit = unit
        else:
            self.unit = ""
        self.enum = enum
        self.script = script
        if self.script is not None:
            self.enum = False
        self.scientific = scientific
        self.conn = False
        self.pv = epics.pv.PV(
            self.pv_name,
            form="ctrl",
            auto_monitor=True,
            connection_callback=self.on_connection_change,
            connection_timeout=0.0001,
        )
        if display_precision < 0:
            self.display_precision = self.pv.precision
        else:
            self.display_precision = display_precision
        super().__init__(
            urwid.Text("Disconnected", align=align_text, wrap="clip"),
            "disconnected",
            focus_map="disconnected",
        )
        if self.enum:
            self.original_widget._selectable = False
        else:
            self.original_widget._selectable = True
        self.pv.add_callback(callback=self.change_value)

        self.infoText = (
            "Widget type: {}\n"
            "PV Name:     {}\n"
            "Enum:        {}\n"
            "Precision:   {}\n"
            "Scientific:  {}\n"
            "Unit:        {}\n"
            "Script:      {}\n".format(
                self.__class__.__name__,
                self.pv_name,
                self.enum,
                self.display_precision,
                self.scientific,
                self.script,
                self.unit,
            )
        )

    def change_value(self, **kw):
        if self.script is None:
            if self.enum:
                self.original_widget.set_text((self.pv.char_value))
            else:
                if self.scientific:
                    self.original_widget.set_text(
                        u"{:.{}e}{}".format(
                            self.pv.value, self.display_precision, self.unit
                        )
                    )
                else:
                    self.original_widget.set_text(
                        u"{:.{}f}{}".format(
                            self.pv.value, self.display_precision, self.unit
                        )
                    )
        else:
            output = subprocess.run(
                "{} {}".format(self.script, self.pv.value),
                shell=True,
                stdout=subprocess.PIPE,
            )
            output = output.stdout.decode("utf-8")
            if output.count("\n") > 1:
                self.original_widget.set_text("Invalid output from string")
            else:
                output = output.replace("\n", "")
                self.original_widget.set_text(output)

    def on_connection_change(self, conn, **kw):
        self.conn = conn
        if conn:
            super().set_attr_map({None: "getPV"})
            super().set_focus_map({None: "getPV_focus"})
        else:
            super().set_attr_map({None: "disconnected"})
            super().set_focus_map({None: "disconnected"})
            self.original_widget.set_text("Disconnected")

    def keypress(self, size, key):
        """
        Handle key strokes
        """
        if key is "p" and not self.enum:
            subprocess.call(
                "ConsolePlot.sh {} {}".format(self.pv_name, 100000), shell=True
            )
        else:
            return key


class LED(urwid.AttrMap):
    """ LED notification widget """

    count = 0

    def __init__(
        self,
        pv_name,
        red_values=[],
        green_values=[],
        yellow_values=[],
        enum=False,
        exclude_selection=False,
        script=None,
    ):
        """

        """
        self.pv_name = pv_name
        self.red_values = red_values
        self.green_values = green_values
        self.yellow_values = yellow_values
        LED.count += 1
        self.enum = enum
        self.script = script
        self.exclude_selection = exclude_selection
        self.__super.__init__(urwid.Divider(), "disconnected")
        self.pv = epics.pv.PV(
            self.pv_name,
            form="ctrl",
            auto_monitor=True,
            connection_callback=self.on_connection_change,
            connection_timeout=0.0001,
        )
        if self.script:
            self.pv.add_callback(callback=self.change_value_script)
        elif self.enum:
            self.pv.add_callback(callback=self.change_value_enum)
        else:
            self.pv.add_callback(callback=self.change_value)

    def change_value_script(self, value, **kw):
        output = subprocess.run(
            "{} {}".format(self.script, value), shell=True, stdout=subprocess.PIPE
        )
        output = output.stdout.decode("utf-8")
        if output.count("\n") > 1:
            super().set_attr_map({None: "head"})  # invalid string
        else:
            output = output.replace("\n", "")
            if self.exclude_selection:
                if (output not in self.red_values) and (self.red_values):
                    super().set_attr_map({None: "red_LED_on"})
                elif (output not in self.yellow_values) and (self.yellow_values):
                    super().set_attr_map({None: "yellow_LED_on"})
                elif (output not in self.green_values) and (self.green_values):
                    super().set_attr_map({None: "green_LED_on"})
                else:
                    super().set_attr_map({None: "LED_off"})
            else:
                if output in self.red_values:
                    super().set_attr_map({None: "red_LED_on"})
                elif output in self.yellow_values:
                    super().set_attr_map({None: "yellow_LED_on"})
                elif output in self.green_values:
                    super().set_attr_map({None: "green_LED_on"})
                else:
                    super().set_attr_map({None: "LED_off"})

    def change_value_enum(self, char_value, **kw):
        if self.exclude_selection:
            if char_value:
                if (char_value.decode("utf8") not in self.red_values) and (
                    self.red_values
                ):
                    super().set_attr_map({None: "red_LED_on"})
                elif (char_value.decode("utf8") not in self.yellow_values) and (
                    self.yellow_values
                ):
                    super().set_attr_map({None: "yellow_LED_on"})
                elif (char_value.decode("utf8") not in self.green_values) and (
                    self.green_values
                ):
                    super().set_attr_map({None: "green_LED_on"})
                else:
                    super().set_attr_map({None: "LED_off"})
        else:
            if char_value:
                if char_value.decode("utf8") in self.red_values:
                    super().set_attr_map({None: "red_LED_on"})
                elif char_value.decode("utf8") in self.yellow_values:
                    super().set_attr_map({None: "yellow_LED_on"})
                elif char_value.decode("utf8") in self.green_values:
                    super().set_attr_map({None: "green_LED_on"})
                else:
                    super().set_attr_map({None: "LED_off"})

    def change_value(self, value, **kw):
        if self.exclude_selection:
            if (value not in self.red_values) and (self.red_values):
                super().set_attr_map({None: "red_LED_on"})
            elif (value not in self.yellow_values) and (self.yellow_values):
                super().set_attr_map({None: "yellow_LED_on"})
            elif (value not in self.green_values) and (self.green_values):
                super().set_attr_map({None: "green_LED_on"})
            else:
                super().set_attr_map({None: "LED_off"})
        else:
            if value in self.red_values:
                super().set_attr_map({None: "red_LED_on"})
            elif value in self.yellow_values:
                super().set_attr_map({None: "yellow_LED_on"})
            elif value in self.green_values:
                super().set_attr_map({None: "green_LED_on"})
            else:
                super().set_attr_map({None: "LED_off"})

    def on_connection_change(self, conn, **kw):
        if conn:
            if self.enum:
                self.change_value_enum(self.pv.char_value)
            else:
                self.change_value(self.pv.value)
        else:
            super().set_attr_map({None: "disconnected"})


class button(urwid.AttrMap):
    """ Control Button """

    count = 0

    def __init__(
        self,
        text,
        pv_name=None,
        click_value=1,
        enum=False,
        script=None,
        align_text="left",
    ):
        """

        """
        self.pv_name = pv_name
        self.click_value = click_value
        self.script = script
        button.count += 1
        if pv_name is not None:
            self.pv = epics.pv.PV(
                self.pv_name, auto_monitor=True, connection_callback=self.on_connection_change, connection_timeout=0.0001
            )
        self.__super.__init__(urwid.Button(text), "None", focus_map="button")
        self.original_widget._label.align = align_text
        urwid.connect_signal(self.original_widget, "click", self.clicked)

        self.infoText = (
            "Widget type: {}\n"
            "PV Name:     {}\n"
            "Click Value: {}\n"
            "Script:      {}\n".format(
                self.__class__.__name__,
                self.pv_name,
                self.click_value,
                self.script,
            )
        )

    def clicked(self, *args):
        if self.script is None:
            self.pv.put(self.click_value)
        else:
            screen.loop.screen.clear()
            if os.path.isfile(bin_path + self.script.split()[0]):
                subprocess.call(bin_path + self.script, shell=True)
            else:
                subprocess.call(self.script, shell=True)
            screen.loop.screen.clear()

    def on_connection_change(self, conn, **kw):
        if conn:
            super().set_attr_map({None: "None"})
            super().set_focus_map({None: "button"})
        else:
            super().set_attr_map({None: "disconnected"})

class WidgetInfoPopUp(urwid.WidgetWrap):
    """A dialog that appears with nothing but a close button """
    signals = ["close"]

    def __init__(self, text, *args, **kwargs):
        close_button = urwid.Button("Close")
        urwid.connect_signal(close_button, "click", lambda button: self._emit("close"))
        pile = urwid.Pile(
            [urwid.Text("Widget Information: \n\n{}".format(text)), urwid.AttrWrap(close_button, "button")]
        )
        fill = urwid.Filler(pile)
        self.__super.__init__(urwid.AttrWrap(fill, "popup"))


class PopUpWrapper(urwid.PopUpLauncher):

    def __init__(self, type, **kwargs):
        self.__super.__init__(str2Class(type)(**kwargs))

    def create_pop_up(self):
        pop_up = WidgetInfoPopUp(self.original_widget.infoText)
        urwid.connect_signal(pop_up, "close", lambda button: self.close_pop_up())
        return pop_up

    def get_pop_up_parameters(self):
        return {"left": 0, "top": 1, "overlay_width": 40, "overlay_height": 10}

    def keypress(self, size, key):
        """
        Handle key strokes
        """
        (maxcol,) = size
        if key in ["i", "I"]:
            self.open_pop_up()
            unhandled = None
        else:
            unhandled = self.original_widget.keypress((maxcol,), key)

        return unhandled


def str2Class(str):
    return getattr(sys.modules[__name__], str)


def parseConfig(file, macro=None, verbose=False, header=None):

    inputFile = open(file, "r")
    readFile = inputFile.read()
    inputFile.close()
    if macro:
        for macroIndex, macroValue in enumerate(macro):
            if "%M{}".format(macroIndex + 1) in readFile:
                if macroValue == "%S":
                    readFile = readFile.replace("%M{}KS".format(macroIndex + 1), '%S')
                    readFile = readFile.replace("%M{}".format(macroIndex + 1), '')
                else:
                    readFile = readFile.replace("%M{}KS".format(macroIndex + 1), macroValue)
                    readFile = readFile.replace("%M{}".format(macroIndex + 1), macroValue)
            else:
                input(
                    "The YAML file {} does not contain any Macro designator [%M{}]. Press any key to evaluate the file normally".format(
                        file, macroIndex + 1
                    )
                )

    pageConfig = yaml.load(readFile)
    inputFile.close()
    rows_list = []
    row_number = 0
    for row in pageConfig:
        row_number += 1
        if verbose:
            print("\n\nThis is a new row [{}] in the GUI".format(row_number))
        columns_list = []
        field_number = 0
        for field in row:
            field_number += 1
            if verbose:
                print(
                    "\nThis is a new field [{}]in row {}".format(
                        field_number, row_number
                    )
                )
                print(field)
            if "device_name" in field:
                field["pv_name"] = field["device_name"] + ":" + field["pv_name"]
                field.pop("device_name")
            fieldType = field["type"]
            fieldWidth = field["width"]
            if fieldType not in ["text", "LED", "getPV", "setPV", "button", "divider"]:
                raise FieldParseError(
                    field, "undefined widget type ({})".format(fieldType)
                )
            field.pop("type")
            field.pop("width")
            if "enable" in field:
                if not field["enable"]:
                    continue
                field.pop("enable")
            columns_list.append(("fixed", fieldWidth, PopUpWrapper(fieldType, **field)))
        rows_list.append(urwid.Columns(columns_list))

    if header:
        return urwid.Columns(columns_list)
    else:
        return urwid.ListBox(urwid.SimpleFocusListWalker(rows_list))


class terminal_client:
    palette = [
        ("None", "light gray", "black"),
        ("body", "black", "light gray"),
        ("popup", "black", "dark gray"),
        ("head", "yellow", "black"),
        ("foot", "light gray", "black"),
        ("title", "white", "black"),
        ("disconnected", "black", "dark magenta"),
        ("getPV", "black", "light blue"),
        ("getPV_focus", "white", "dark blue"),
        ("setPV", "black", "dark cyan"),
        ("setPV_focus", "black", "light cyan"),
        ("setPV_edit", "dark red", "light cyan"),
        ("LED_off", "black", "dark gray"),
        ("green_LED_on", "black", "light green"),
        ("red_LED_on", "black", "light red"),
        ("yellow_LED_on", "black", "yellow"),
        ("button", "light gray", "dark blue"),
    ]

    footer_text = [
        ("title", "Testing Grounds"),
        "    ",
        ("key", "UP"),
        ",",
        ("key", "DOWN"),
        ",",
        ("key", "RIGHT"),
        ",",
        ("key", "LEFT"),
        "  ",
        ("key", "ENTER"),
        "  ",
        ("key", "+"),
        ",",
        ("key", "-"),
        "  ",
        ("key", "LEFT"),
        "  ",
        ("key", "HOME"),
        "  ",
        ("key", "END"),
        "  ",
        ("key", "CTRL+l: Redraw Screen"),
        "  ",
        ("key", "Q: Exit"),
    ]

    # update_rate = 0.5

    def __init__(
        self,
        configFileName,
        update_rate=0.5,
        headerConfigFileName=None,
        macro=None,
        verbose=False,
    ):

        self.update_rate = update_rate
        if verbose:
            print("Parsing config file: {}".format(configFileName))
        self.walker = parseConfig(configFileName, macro=macro, verbose=verbose)
        if headerConfigFileName:
            if verbose:
                print("Parsing header file: {}".format(headerConfigFileName))
            self.header = parseConfig(
                headerConfigFileName, verbose=verbose, header=True
            )
        else:
            self.header = urwid.Text(u"Terminal EPICS Client")
        self.footer = urwid.AttrMap(urwid.Text(self.footer_text), "foot")
        self.view = urwid.Frame(
            urwid.AttrMap(self.walker, "body"),
            header=urwid.AttrMap(self.header, "head"),
            footer=self.footer,
        )
        self.EventLoop = urwid.SelectEventLoop()
        self.EventLoop.alarm(self.update_rate, self.update_screen)

    def main(self):
        """Run the program."""

        self.loop = urwid.MainLoop(
            self.view,
            self.palette,
            unhandled_input=self.unhandled_input,
            event_loop=self.EventLoop,
            pop_ups=True,
        )
        self.loop.run()

    def unhandled_input(self, k):
        # Exit program
        if k in ("q", "Q"):
            raise urwid.ExitMainLoop()

    def update_screen(self):
        self.EventLoop.alarm(self.update_rate, self.update_screen)


def main():
    terminal_client("test.yaml").main()


if __name__ == "__main__":
    args = parser.parse_args()
    if args.config:
        if os.path.isfile(yaml_path + args.config):
            screen = terminal_client(
                yaml_path + args.config,
                headerConfigFileName=args.header,
                macro=args.macro,
                verbose=args.verbose,
            )
        else:
            screen = terminal_client(
                args.config,
                update_rate=args.time,
                headerConfigFileName=args.header,
                macro=args.macro,
                verbose=args.verbose,
            )
        screen.main()
    else:
        print("Please define a YAML configuration file using -c")
