# -*- coding: utf-8 -*-
# ANoise AppIndicator 1.0 (Ambient Noise AppIndicatro)
#
# ANoise is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 3 of the License, or
# (at your option) any later version.
#
# ANoise is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with ANoise; if not, see http://www.gnu.org/licenses
# for more information.

# ........................................................................... #
import os

import signal
import threading
import webbrowser

# ........................................................................... #
import gi

gi.require_version('Gtk', '3.0')
gi.require_version('AppIndicator3', '0.1')

# adding noqa E402 linter exceptions because the version number have to be
# specified via a call before having the import statement
from gi.repository import Gtk  # noqa: E402
from gi.repository import AppIndicator3  # noqa: E402

# ........................................................................... #
from preferences import Preferences  # noqa: E402

# ........................................................................... #
APPINDICATOR_ID = 'anoise-indicator'
APPINDICATOR_ICON = 'anoise-indicator-symbolic'
APPINDICATOR_ICON_PAUSE = 'anoise-indicator-pause-symbolic'
APPINDICATOR_ICONS_FALLBACK = [
    'media-playback-start-symbolic',
    'media-playback-pause-symbolic'
]
PLAYING_NOW_FALLBACK_ICON = 'audio-card-symbolic'


# ........................................................................... #
class Indicator:

    # ----------------------------------------------------------------------- #
    def __init__(self, player):

        # apparently appindicator will not quit on Ctrl-C by default. fix
        # bellow allows it to do so in Ctrl-C run the default action kernel
        # action which allows indicator to exit
        signal.signal(signal.SIGINT, signal.SIG_DFL)

        # expose the passing player to tht class
        self._player = player

        # remove registration to dbus, disabling MPRIS integration, mainly this
        # is done because current anoise MPRIS integration does not notify the
        # GUI element of play/pause/next/forward changes internally an attempt
        # at dbus manager that listens for anoise mpris notification fails due
        # to double signaling and handling of multiple MPRIS subscribed clients
        # and inability to distinguish which come from anoise
        self._player.sound_menu.remove_from_connection()

        #: DEBUG SETTING, used during development
        #: hide window ui, if it's the GUI class (rather then Indicator class)
        # if self._player.window.__class__.__name__ == 'GUI':
        #     self._player.window.window.hide()

        # build the preferences window
        self._preferences_window = Preferences(self)

        # expose the default gtk settings
        self._gtk_settings = Gtk.Settings.get_default()

        # expose the default icon theme
        self._default_icon_theme = Gtk.IconTheme.get_default()

        # expose "hicolor" theme as fallback theme
        self._fallback_icon_theme = Gtk.IconTheme()
        self._fallback_icon_theme.set_custom_theme('hicolor')

        # expose found appindicator and appindicator-pause icons
        self._appindicator_icon, self._appindicator_icon_pause = \
            self._get_indicator_icons()

        # build the appindicator
        self._appindicator, builder = self._make_appindicator()

        # expose the play/pause menu item to the class
        self._menuitem_play = builder.get_object('play_pause_toggle')
        # expose now playing menu item
        self._menuitem_now_playing = builder.get_object('now_playing')

        # expose now playing image
        self._image_now_playing = builder.get_object('image_now_playing')
        # expose play image
        self._image_play = builder.get_object('image_play')
        # expose pause image
        self._image_pause = builder.get_object('image_pause')

        # disable startup autoplay (ugh, terrible approach)
        # runs before indicator is made visible to show the "paused" icon
        self._disable_startup_autoplay()

        # set the indicator status to active
        self._appindicator.set_status(AppIndicator3.IndicatorStatus.ACTIVE)

        # update the noise icon in the ui and the appindicator
        self._update_now_playing()

    # ----------------------------------------------------------------------- #
    def set_timer(self, enable, seconds):
        # method is run by preferences window code, which is why it's public

        # it's strange that this code is run in the UI code.
        # if window ui and appindicator will both install you will end up with
        # two timers, so seems like runing both "ui"s is not a good idea
        # exclusive, unless preferences can be a singleton

        if enable:
            self.timer = threading.Timer(seconds, self._set_future_pause)
            self.timer.start()
        else:
            self.timer.cancel()

    # ----------------------------------------------------------------------- #
    def _disable_startup_autoplay(self):
        """
        Disable auto play on aplication startup. This is done by patching
        the self._player._sound_menu_play with function that pauses the player
        insteady of playing it, and the restores the original function after it
        was ran once. Unfortunately this is the only way to do this at this
        point.
        """

        # set all the gui statuses to "pause"
        self._pause()
        # preserve the original function
        original_func = self._player._sound_menu_play

        # create a patched function which pauses the play when run the FIRST
        # time and then restores the original _sound_menu_play to the player
        # object (sad, should not need to patch)
        def _sound_menu_play(*args, **kwargs):
            # pause
            self._player._sound_menu_pause()
            self._player._sound_menu_play = original_func

        # now patch the play function with our patched function
        self._player._sound_menu_play = _sound_menu_play

    # ----------------------------------------------------------------------- #
    def _make_appindicator(self):
        """
        Return constructed AppIndicator and it's menu.
        Also return the menu builder so we can update few of it's items
        """

        # get full glade file. assumption here is that the ui file in the same
        # folder as this script
        ui_file_path = os.path.join(
            os.path.realpath(os.path.dirname(__file__)),
            'appindicator.ui'
        )

        # force showing of images despite whatever the global setting is
        self._gtk_settings.props.gtk_button_images = True

        # build the apindicator menu from the glade file
        builder = Gtk.Builder()
        builder.add_from_file(ui_file_path)

        # create the appindicator
        appindicator = AppIndicator3.Indicator.new(
            APPINDICATOR_ID,
            self._appindicator_icon,
            AppIndicator3.IndicatorCategory.APPLICATION_STATUS
        )

        # get the appindicator menu
        menu = builder.get_object('appindicator_menu')

        # setup the signals for the appindicator menu items
        builder.connect_signals(self)

        # get the play/pause menu iterm
        menuitem_play = builder.get_object('play_pause_toggle')

        # setup to trigger play/pause menu action on appindicator middle click
        appindicator.set_secondary_activate_target(menuitem_play)

        # set all menu items visible
        menu.show_all()

        # attach to the menu to the appindicator
        appindicator.set_menu(menu)

        return appindicator, builder

    # ----------------------------------------------------------------------- #
    def _get_indicator_icons(self):

        icons = []

        # for over both default and fallback theme to get icons
        for theme in [self._default_icon_theme, self._fallback_icon_theme]:
            # try to find both regular and pause icons
            for icon_name in [APPINDICATOR_ICON, APPINDICATOR_ICON_PAUSE]:
                # break out of the loop if we failed to find any of the icons
                # and set the icon collection to an empty list
                if theme.has_icon(icon_name) is True:
                    icon_info = theme.lookup_icon(icon_name,
                                                  Gtk.IconSize.MENU, 0)
                    # get icon file path
                    icons.append(icon_info.get_filename())
                else:
                    icons = []
                    break

            # if we found both icons break out
            if len(icons) == 2 or all(icons) is True:
                break

        # if we could not find 2 icons fallback to very generic icons
        if len(icons) != 2 or all(icons) is False:
            icons = APPINDICATOR_ICONS_FALLBACK

        return icons

    # ----------------------------------------------------------------------- #
    def _on_toggle_play_pause_activate(self, widget):
        if self._player.is_playing:
            self._player._sound_menu_pause()
            self._pause()
        else:
            self._player._sound_menu_play()
            self._play()

    # ----------------------------------------------------------------------- #
    def _on_next_activate(self, widget):
        # tell the player to play next track
        self._player._set_new_play('next')
        # update noise status
        self._update_now_playing()

    # ----------------------------------------------------------------------- #
    def _on_previous_activate(self, widget):
        # tell the player to play track
        self._player._set_new_play('previous')
        # update noise status
        self._update_now_playing()

    # ----------------------------------------------------------------------- #
    def _on_preferences_window_show_activate(self, widget):
        self._preferences_window.show()

    # ----------------------------------------------------------------------- #
    def _on_about_activate(self, widget):
        # open default web browser to the homepage
        webbrowser.open_new('http://anoise.tuxfamily.org')

    # ----------------------------------------------------------------------- #
    def _on_quit_activate(self, widget):
        # try to cancel the timer catching all (really?) exceptions
        try:
            self.timer.cancel()
        except Exception:
            pass

        # tell gtk main loop to quit
        Gtk.main_quit()

    # ----------------------------------------------------------------------- #
    def _update_now_playing(self):
        # try to get the noise icon file, otherwise fallback to the default
        # note: it does not throw a specific error we can test for so
        #       we are testing for Exception
        try:
            # get the icon file name for the existing noise
            icon_file = self._player.noise.get_icon().replace('file://', '')
            fallback_icon_name = None
        except Exception:
            # retrieve the default application icon from the icon as a pixbuf
            icon_file = APPINDICATOR_ICON
            fallback_icon_name = PLAYING_NOW_FALLBACK_ICON

        # get the now playing noise
        now_playing = self._player.noise.get_name()
        # form "Not Playing: <noise>" string for the indicator
        new_label = "Now Playing: %s" % now_playing
        # update the indicator now playing label to the noise name
        self._menuitem_now_playing.set_label(new_label)

        # update the now playing menu icon
        #
        # if fallback icon name is not set then we set the found noise icon
        # otherwise we set the set the image to the fallback icons
        if fallback_icon_name is None:
            self._image_now_playing.set_from_file(icon_file)
        else:
            self._image_now_playing.set_from_icon_name(fallback_icon_name,
                                                       Gtk.IconSize.MENU)

        # update the now playing menu item with the now playing image
        self._menuitem_now_playing.set_image(self._image_now_playing)

    # ----------------------------------------------------------------------- #
    def _play(self):
        # tell player to play
        self._menuitem_play.set_label("P_ause")
        self._menuitem_play.set_image(self._image_pause)
        self._appindicator.set_icon(self._appindicator_icon)
        self._update_now_playing()

    # ----------------------------------------------------------------------- #
    def _pause(self):
        # pause the player
        self._menuitem_play.set_label("_Play")
        self._menuitem_play.set_image(self._image_play)
        self._appindicator.set_icon(self._appindicator_icon_pause)
        self._update_now_playing()

    # ----------------------------------------------------------------------- #
    def _set_future_pause(self):
        self._preferences_window.set_show_timer()
        self._player._sound_menu_pause()
        self._pause()


# ........................................................................... #
# anoise gui class integration
GUI = Indicator
