#!/usr/bin/env python3


import epics
import argparse
import shutil
import os
import sys
import fileinput
from threading import Thread
from time import sleep
import urwid
from urwid import (CURSOR_LEFT, CURSOR_RIGHT, CURSOR_UP, CURSOR_DOWN, REDRAW_SCREEN)
import yaml
import subprocess

screen = None

parser = argparse.ArgumentParser()
parser.add_argument('-c', '--config', help='YAML file with page configuration')
parser.add_argument('-m', '--macro', help='replace every "%M" with this given value')
parser.add_argument('-v','--verbose', help="increase output verbosity", action="store_true")

divider = urwid.Divider
text = urwid.Text
fill = urwid.SolidFill

try:
    TEC_path = os.environ['TEC_PATH']
    bin_path = TEC_path + '/bin/'
    yaml_path = TEC_path + '/YAML/'
except KeyError:
    print('(TEC_PATH) environement variable not defined, please define it in your .bashrc file or similar')
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
        self.message = '{} in field\n{}'.format(message, field)


class float_edit(urwid.Edit):
    """Container widget for writing to float output PVs"""
    count = 0

    def valid_char(self, ch):
        """
        Return true for decimal digits, decimal point and a negative sign.
        """
        return len(ch) == 1 and ch in "0123456789.-"

    def __init__(self, pv_name, align_t='left', display_precision=-1):
        """
        Initializing float_edit widget in 'disconnected' mode
        """
        self.pv_name = pv_name
        self.count += 1
        self.pv = epics.pv.PV(self.pv_name, auto_monitor=True, connection_timeout=0.00001)
        self.conn = False
        if display_precision < 0:
            self.display_precision = self.pv.precision
        else:
            self.display_precision = display_precision
        self.__super.__init__(edit_text='Disconnected', wrap='clip', align=align_t)

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
        p = self.edit_pos

        if self._command_map[key] == CURSOR_LEFT:
            if p == 0:
                return None
        elif self._command_map[key] == CURSOR_RIGHT:
            if p >= len(self.edit_text):
                return None
        elif self._command_map[key] == CURSOR_UP:
            if p >= len(self.edit_text) or self.edit_text[p] == '.' or self.edit_text[p] == '-':
                return None
            point_pos = self.edit_text.find('.')
            if point_pos >= 0:
                if point_pos < p:
                    super().set_edit_text('{:.{}f}'.format(float(self.edit_text) + (10 ** (-1 * (p - point_pos))), self.display_precision))
                else:
                    super().set_edit_text('{:.{}f}'.format(float(self.edit_text) + (10 ** (-1 * (p + 1 - point_pos))), self.display_precision))
            else:
                super().set_edit_text('{}'.format(int(self.edit_text) + (10 ** (len(self.edit_text) - p - 1))))
            self.write_value()
            return None
        elif self._command_map[key] == CURSOR_DOWN:
            if 0 or p >= len(self.edit_text) or self.edit_text[p] == '.' or self.edit_text[p] == '-':
                return None
            point_pos = self.edit_text.find('.')
            if point_pos >= 0:
                if point_pos < p:
                    super().set_edit_text('{:.{}f}'.format(float(self.edit_text) - (10 ** (-1 * (p - point_pos))), self.display_precision))
                else:
                    if self.edit_text[p] == 1:
                        next_non_zero_index = self.edit_text.match('[1-9]', p + 1)
                        super().set_edit_text('{:.{}f}'.format(float(self.edit_text) - (10 ** (-1 * (next_non_zero_index - point_pos))), self.display_precision))
                    else:
                        super().set_edit_text('{:.{}f}'.format(float(self.edit_text) - (10 ** (-1 * (p + 1 - point_pos))), self.display_precision))
            else:
                super().set_edit_text('{}'.format(int(self.edit_text) - (10 ** (len(self.edit_text) - p - 1))))
            self.write_value()
            return None
        elif key == '.' and key in self.edit_text:
            return None
        elif key == '-' and p != 0:
            return None

        unhandled = super().keypress((maxcol, ), key)

        return unhandled

    def write_value(self):
        """
        write the value to the PV
        """
        if self.edit_text == '' or self.edit_text == '-' or self.edit_text == '.' or self.edit_text == '-.':
            super().set_edit_text("{:.{}f}".format(self.pv.get(), self.display_precision))
        else:
            self.pv.put(float(self.edit_text))

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
            return float(self.edit_text)
        else:
            return 0


class analog_input(urwid.AttrMap):
    """Container widget for reading analog input PVs"""
    count = 0

    def __init__(self, pv_name, enum=False, display_precision=-1, unit=None, align_text='left'):
        self.pv_name = pv_name
        self.count += 1
        if unit is not None:
            self.unit = unit
        else:
            self.unit = ''
        self.enum = enum
        self.conn = False
        self.pv = epics.pv.PV(self.pv_name, form='ctrl', auto_monitor=True, connection_callback=self.on_connection_change, connection_timeout=0.00001)
        if display_precision < 0:
            self.display_precision = self.pv.precision
        else:
            self.display_precision = display_precision
        super().__init__(urwid.Text('Disconnected', align=align_text, wrap='clip'), 'disconnected')
        self.pv.add_callback(callback=self.change_value)

    def change_value(self, **kw):
        if self.enum:
            self.original_widget.set_text((self.pv.char_value))
        else:
            self.original_widget.set_text(u'{:.{}f}{}'.format(self.pv.value, self.display_precision, self.unit))

    def on_connection_change(self, conn, **kw):
        self.conn = conn
        if conn:
            super().set_attr_map({None: 'analog_input'})
        else:
            super().set_attr_map({None: 'disconnected'})
            self.original_widget.set_text('Disconnected')


class analog_output(urwid.AttrMap):
    """container widget to pass color when editing values"""
    count = 0

    def __init__(self, pv_name, display_precision=-1, align_text='left'):
        """
        
        """
        self.pv_name = pv_name
        self.count += 1
        self.display_precision = display_precision
        self.editing = False
        self.__super.__init__(float_edit(self.pv_name, align_t=align_text, display_precision=self.display_precision), 'disconnected', focus_map='disconnected')
        self.original_widget.pv.connection_callbacks.append(self.on_connection_change)
        self.original_widget.pv.add_callback(callback=self.change_value)

    def keypress(self, size, key):
        """
        Handle enter key to start editing the contents of the field, pass everything else to the parent
        """
        (maxcol,) = size
        
        if self.original_widget.conn:
            if key == "enter":
                if self.editing:
                    self.editing = False
                    point_pos = self.original_widget.edit_text.find('.')
                    if point_pos >= 0 and self.original_widget.edit_text != '.' and self.original_widget.edit_text != '-.':
                        self.original_widget.set_edit_text('{:.{}f}'.format(float(self.original_widget.edit_text), self.original_widget.display_precision))
                    super().set_focus_map({None: 'analog_output_focus'})
                    self.original_widget.write_value()
                else:
                    self.editing = True
                    super().set_focus_map({None: 'analog_output_edit'})
                    self.original_widget.set_edit_pos(0)
                return None
        else:
            self.editing = False

        if self.editing:
            unhandled = self.original_widget.keypress((maxcol, ), key)
        else:
            unhandled = key

        return unhandled

    def on_connection_change(self, conn, **kw):
        self.original_widget.conn = conn
        if conn:
            super().set_attr_map({None: 'analog_output'})
            super().set_focus_map({None: 'analog_output_focus'})
        else:
            self.editing = False
            super().set_attr_map({None: 'disconnected'})
            super().set_focus_map({None: 'disconnected'})
            self.original_widget.set_edit_text('Disconnected')

    def change_value(self, **kw):
        self.original_widget.set_edit_text(u'{:.{}f}'.format(self.original_widget.pv.value, self.display_precision))


class LED(urwid.AttrMap):
    """ LED notification widget """

    count = 0

    def __init__(self, pv_name, red_values=[None], green_values=[None], yellow_values=[None], enum=False):
        """
        
        """
        self.pv_name = pv_name
        self.red_values = red_values
        self.green_values = green_values
        self.yellow_values = yellow_values
        self.count += 1
        self.enum = enum
        self.__super.__init__(urwid.Divider(), 'disconnected')
        self.pv = epics.pv.PV(self.pv_name, form='ctrl', auto_monitor=True, connection_callback=self.on_connection_change, connection_timeout=0.00001)
        if self.enum:
            self.pv.add_callback(callback=self.change_value_enum)
        else:
            self.pv.add_callback(callback=self.change_value)

    def change_value_enum(self, char_value, **kw):
        if char_value:
            if char_value.decode('utf8') in self.red_values:
                super().set_attr_map({None: 'red_LED_on'})
            elif char_value.decode('utf8') in self.yellow_values:
                super().set_attr_map({None: 'yellow_LED_on'})
            elif char_value.decode('utf8') in self.green_values:
                super().set_attr_map({None: 'green_LED_on'})
            else:
                super().set_attr_map({None: 'LED_off'})

    def change_value(self, value, **kw):
        if value in self.red_values:
            super().set_attr_map({None: 'red_LED_on'})
        elif value in self.yellow_values:
            super().set_attr_map({None: 'yellow_LED_on'})
        elif value in self.green_values:
            super().set_attr_map({None: 'green_LED_on'})
        else:
            super().set_attr_map({None: 'LED_off'})

    def on_connection_change(self, conn, **kw):
        if conn:
            if self.enum:
                self.change_value_enum(self.pv.char_value)
            else:
                self.change_value(self.pv.value)
        else:
            super().set_attr_map({None: 'disconnected'})


class button(urwid.AttrMap):
    """ Control Button """

    count = 0

    def __init__(self, text, pv_name=None, click_value=1, enum=False, run_script=None, align_text='left'):
        """
        
        """
        self.pv_name = pv_name
        self.click_value = click_value
        self.run_script = run_script
        self.count += 1
        if pv_name is not None:
            self.pv = epics.pv.PV(self.pv_name, auto_monitor=True, connection_timeout=0.00001)
        self.__super.__init__(urwid.Button(text), 'None',focus_map='button')
        self.original_widget._label.align = align_text
        urwid.connect_signal(self.original_widget, 'click', self.clicked)

    def clicked(self, *args):
        if self.run_script is None:
            self.pv.put(self.click_value)
        else:
            screen.loop.screen.clear()
            subprocess.call(bin_path + self.run_script, shell=True)
            screen.loop.screen.clear()


def str2Class(str):
    return getattr(sys.modules[__name__], str)


def parseConfig(file, macro, verbose=False):

    inputFile = open(file, 'r')
    readFile = inputFile.read()
    inputFile.close()

    if macro:
        if '%M' in readFile:
            readFile = readFile.replace('%M', macro)
            
        else:
            input('The YAML file does not contain any Macro designator [%M]. Press any key to evaluate the file normally')
      


    pageConfig = yaml.load(readFile)
    inputFile.close()
    rows_list = []
    row_number=0
    for row in pageConfig:
        row_number += 1
        if verbose:
            print('\n\nThis is a new row [{}] in the GUI'.format(row_number))
        columns_list = []
        field_number = 0
        for field in row:
            field_number += 1
            if verbose:
                print('\nThis is a new field [{}]in row {}'.format(field_number, row_number))
                print(field)
            if "device_name" in field:
                field['pv_name'] = field['device_name'] + ':' + field['pv_name']
                field.pop('device_name')
            fieldType = field['type']
            fieldWidth = field['width']
            if fieldType not in ['text', 'LED', 'analog_input', 'analog_output', 'button', 'divider']:
                raise FieldParseError(field, 'undefined widget type ({})'.format(fieldType))
            field.pop('type')
            field.pop('width')
            columns_list.append(('fixed', fieldWidth, str2Class(fieldType)(**field)))
        rows_list.append(urwid.Columns(columns_list))

    return urwid.ListBox(urwid.SimpleFocusListWalker(rows_list))


class terminal_client:
    palette = [
        ('None', 'light gray', 'black'),
        ('body', 'black', 'light gray'),
        ('head', 'yellow', 'black'),
        ('foot', 'light gray', 'black'),
        ('title', 'white', 'black'),
        ('disconnected', 'black', 'dark magenta'),
        ('analog_input', 'black', 'light blue'),
        ('analog_output', 'black', 'dark cyan'),
        ('analog_output_focus', 'black', 'light cyan'),
        ('analog_output_edit', 'dark red', 'light cyan'),
        ('LED_off', 'black', 'dark gray'),
        ('green_LED_on', 'black', 'light green'),
        ('red_LED_on', 'black', 'light red'),
        ('yellow_LED_on', 'black', 'yellow'),
        ('button', 'light gray', 'dark blue')
        ]

    footer_text = [
        ('title', "Testing Grounds"), "    ",
        ('key', "UP"), ",", ('key', "DOWN"), ",",
        ('key', "RIGHT"), ",", ('key', "LEFT"),
        "  ",
        ('key', "ENTER"), "  ",
        ('key', "+"), ",",
        ('key', "-"), "  ",
        ('key', "LEFT"), "  ",
        ('key', "HOME"), "  ",
        ('key', "END"), "  ",
        ('key', "CTRL+l: Redraw Screen"), "  ",
        ('key', "Q: Exit"),
        ]

    update_rate = 0.1

    def __init__(self, configFileName, macro=None, verbose=False):

        self.walker = parseConfig(configFileName, macro, verbose)
        self.header = urwid.Text(u"Terminal EPICS Client")
        self.footer = urwid.AttrMap(urwid.Text(self.footer_text), 'foot')
        self.view = urwid.Frame(
            urwid.AttrMap(self.walker, 'body'),
            header=urwid.AttrMap(self.header, 'head'),
            footer=self.footer)
        self.EventLoop = urwid.SelectEventLoop()
        self.EventLoop.alarm(self.update_rate, self.update_screen)

    def main(self):
        """Run the program."""

        self.loop = urwid.MainLoop(self.view, self.palette, unhandled_input=self.unhandled_input, event_loop=self.EventLoop)
        self.loop.run()

    def unhandled_input(self, k):
        # Exit program
        if k in ('q', 'Q'):
            raise urwid.ExitMainLoop()

    def update_screen(self):
        self.EventLoop.alarm(self.update_rate, self.update_screen)


def main():
    terminal_client('test.yaml').main()


if __name__ == '__main__':
    args = parser.parse_args()

    if args.config:
        if os.path.isfile(yaml_path + args.config):
            screen = terminal_client(yaml_path + args.config, args.macro, args.verbose)
        else:
            screen = terminal_client(args.config, args.macro, args.verbose)
        screen.main()
    else:
        print('Please define a YAML configuration file using -c')
