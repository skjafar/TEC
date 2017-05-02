#!/usr/local/bin/python3


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


parser = argparse.ArgumentParser()
parser.add_argument('-c', '--config', help='YAML file with page configuration')





divider = urwid.Divider
text = urwid.Text

class float_edit(urwid.Edit):
    """Container widget for writing to float output PVs"""
    count = 0

    def valid_char(self, ch):
        """
        Return true for decimal digits, decimal point and a negative sign.
        """
        return len(ch) == 1 and ch in "0123456789.-"

    def __init__(self, pv_name, display_precision=-1, unit=None):
        """
        
        """
        self.pv_name = pv_name
        self.count += 1
        if unit != None:
            self.unit = unit
        else:
            self.unit = ''
        self.pv = epics.pv.PV(self.pv_name, auto_monitor=True)
        if display_precision < 0:
            self.display_precision = self.pv.precision
        else:
            self.display_precision = display_precision
        self.pv.get()
        val = "{:.{}f}".format(self.pv.get(), self.display_precision)
        self.__super.__init__(edit_text=val, wrap='clip')

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
                        next_non_zero_index = self.edit_text.match('[1-9]', p+1)
                        super().set_edit_text('{:.{}f}'.format(float(self.edit_text) - (10 ** (-1 * (next_non_zero_index - point_pos))), self.display_precision))
                    else:
                        super().set_edit_text('{:.{}f}'.format(float(self.edit_text) - (10 ** (-1 * (p + 1 - point_pos))), self.display_precision))
            else:
                super().set_edit_text('{}'.format(int(self.edit_text) - (10 ** (len(self.edit_text)- p - 1))))
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

    def __init__(self, pv_name, enum=False, display_precision=-1, unit=None):
        self.pv_name = pv_name
        self.count += 1
        if unit != None:
            self.unit = unit
        else:
            self.unit = ''
        self.enum = enum
        self.pv = epics.pv.PV(self.pv_name, form='ctrl', auto_monitor=True, connection_callback=self.on_connection_change)
        if display_precision < 0:
            self.display_precision = self.pv.precision
        else:
            self.display_precision = display_precision
        if self.enum:
            super().__init__(urwid.Text(((self.pv.char_value)), wrap='clip'), 'analog_input')
        else:
            super().__init__(urwid.Text((u'{:.{}f}{}'.format(self.pv.value, self.display_precision, self.unit)), wrap='clip'), 'analog_input')
        self.pv.add_callback(callback=self.change_value)

    def change_value(self, **kw):
        if self.enum:
            self.original_widget.set_text((self.pv.char_value))
        else:
            self.original_widget.set_text(u'{:.{}f}{}'.format(self.pv.value, self.display_precision, self.unit))

    def on_connection_change(self, conn, **kw):
        if conn == True:
            super().set_attr_map({None: 'disconnected'})


class analog_output(urwid.AttrMap):
    """container widget to pass color when editing values"""
    count = 0

    def __init__(self, pv_name, display_precision=-1, unit=None):
        """
        
        """
        self.pv_name = pv_name
        self.count += 1
        self.unit = unit
        self.display_precision = display_precision
        self.editing = False
        self.__super.__init__(float_edit(self.pv_name, self.display_precision, self.unit), 'analog_output', focus_map='analog_output_focus')
        self.original_widget.pv.connection_callbacks.append(self.on_connection_change)

    def keypress(self, size, key):
        """
        Handle enter key to start editing the contents of the field, pass everything else to the parent
        """
        (maxcol,) = size

        if key == "enter":
            if self.editing:
                self.editing = False
                point_pos = self.original_widget.edit_text.find('.')
                if point_pos >= 0 and self.original_widget.edit_text != '.' and self.original_widget.edit_text != '-.' :
                    self.original_widget.set_edit_text('{:.{}f}'.format(float(self.original_widget.edit_text), self.original_widget.display_precision))
                super().set_focus_map({None: 'analog_output_focus'})
                self.original_widget.write_value()
            else:
                self.editing = True
                super().set_focus_map({None: 'analog_output_edit'})
                self.original_widget.set_edit_pos(0)
            return None

        if self.editing:
            unhandled = self.original_widget.keypress((maxcol, ), key)
        else:
            unhandled = key

        return unhandled

    def on_connection_change(self, connt, **kw):
        if conn == 'False':
            super().set_attr_map({None: 'disconnected'})
        # This does not work, fix it


class LED(urwid.AttrMap):
    """ LED notification widget """

    count = 0

    def __init__(self, pv_name, on_values=[1], color='green', enum_value=False):
        """
        
        """
        self.pv_name = pv_name
        self.on_values = on_values
        self.count += 1
        self.enum_value = enum_value
        self.color = color
        self.__super.__init__(urwid.Divider(), '{}_LED_off'.format(self.color))
        self.pv = epics.pv.PV(self.pv_name, form='ctrl', auto_monitor=True, connection_callback=self.on_connection_change)
        if self.enum_value:
            self.pv.add_callback(callback=self.change_value_enum)
            self.change_value_enum(self.pv.char_value)
        else:
            self.pv.add_callback(callback=self.change_value)
            self.change_value(self.pv.value)

    def change_value_enum(self, char_value, **kw):
        if char_value.decode('utf8') in self.on_values:
            super().set_attr_map({None: '{}_LED_on'.format(self.color)})
        else:
            super().set_attr_map({None: '{}_LED_off'.format(self.color)})

    def change_value(self, value, **kw):
        if value in self.on_values:
            super().set_attr_map({None: '{}_LED_on'.format(self.color)})
        else:
            super().set_attr_map({None: '{}_LED_off'.format(self.color)})

    def on_connection_change(self, conn, **kw):
        if conn == 'False':
            super().set_attr_map({None: 'disconnected'})

class button(urwid.AttrMap):
    """ Control Button """

    count = 0

    def __init__(self, text, pv_name, click_value=1, enum_value=False):
        """
        
        """
        self.pv_name = pv_name
        self.click_value = click_value
        self.count += 1
        self.__super.__init__(urwid.Button(text), 'None', focus_map='button')
        urwid.connect_signal(self.original_widget, 'click', self.clicked)  
        self.pv = epics.pv.PV(self.pv_name, auto_monitor=True)

    def clicked(self, *args):
        self.pv.put(self.click_value)


def str2Class(str):
    return getattr(sys.modules[__name__], str)


def parseConfig(file):
    
    inputFile = open(file, 'r')
    pageConfig = yaml.load(inputFile)
    inputFile.close()

    rows_list = []
    for row, rowContent in pageConfig.items():
        columns_list = []
        for field in rowContent:
            fieldType = field['type']
            fieldWidth = field['width']
            field.pop('type')
            field.pop('width')
            columns_list.append(('fixed', fieldWidth, str2Class(fieldType)(**field)))
        rows_list.append(urwid.Columns(columns_list))

    #columns_list = []
    #for PV in testPVfromConfig:
    #    columns_list.append(('fixed', 10, PV))

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
        ('green_LED_off', 'black', 'dark gray'),
        ('green_LED_on', 'black', 'light green'),
        ('red_LED_off', 'black', 'dark gray'),
        ('red_LED_on', 'black', 'light red'),
        ('yellow_LED_off', 'black', 'dark gray'),
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
        ('key', "CTRL+l"), " ",
        ('key', "Q"),
        ]

    update_rate = 0.1

    def __init__(self, configFileName):
                
        #self.testPV = []
        #self.testPV.append(analog_input('powerHost:ai1', False, 3, unit='A'))
        #self.testPV.append(analog_input('powerHost:subExample', False, 3, unit='A'))
        #self.testPV.append(analog_input('SRC01-PS-QD1:getStateSequencer', True, 3, unit='A'))
        #self.testPV.append(analog_input('SR-PS-SF1:getIload', False, 3, unit='A'))
        #self.testPV.append(analog_input('SR-PS-SD1:getIload', False, 3, unit='A'))

        
        #self.columns_list = parseConfig('test.yaml')
        #self.columns_list = []
        #for PV in self.testPVfromConfig:
        #    self.columns_list.append(('fixed', 10, PV))

        #print(yaml.dump(self.textPV))
        #print()
        #print(self.textPV)
        #sleep(5)

        #self.columns1 = urwid.Columns(self.columns_list, 1, min_width=5)
        #self.columns1 = parseConfig('test.yaml')
        #self.columns2 = urwid.Columns([('fixed', 9, analog_output('powerHost:ai1', 3, unit='A')),
        #                ('fixed', 9, analog_output('powerHost:subExample', 3, unit='A'))], 1, min_width=5)
        #self.columns3 = urwid.Columns([('fixed', 9, analog_output('SR-PS-BM:getIload', 3, unit='A')),
        #                ('fixed', 9, analog_output('powerHost:ai1', 3, unit='A')),
        #                ('fixed', 2, LED('SR-PS-BM:getStateSequencer', ['Auto', 'Auto Active'], 'green', enum_value=True)),
        #                ('fixed', 2, LED('powerHost:subExample', [5], 'red')),
        #                ('fixed', 10, button(u'Button', 'powerHost:subExample', 5)),
        #                ('fixed', 9, analog_output('powerHost:calc3', 3, unit='A'))], 0, min_width=5)

        #self.walker = urwid.ListBox(urwid.SimpleFocusListWalker([self.columns1, self.columns2, self.columns3]))
        self.walker = parseConfig(configFileName)
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
        # update display of focus directory
        if k in ('q', 'Q'):
            raise urwid.ExitMainLoop()

    def update_screen(self):
        self.EventLoop.alarm(self.update_rate, self.update_screen)


def main():
    terminal_client('test.yaml').main()


if __name__ == '__main__':
    args = parser.parse_args()
    
    if args.config:
        terminal_client(args.config).main()
    else:
        terminal_client('test.yaml').main()