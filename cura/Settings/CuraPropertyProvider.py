# Copyright (c) 2017 Ultimaker B.V.
# Cura is released under the terms of the AGPLv3 or higher.

from PyQt5.QtCore import pyqtProperty, pyqtSignal

from UM.Application import Application
from UM.Settings.Models.SettingPropertyProvider import SettingPropertyProvider
from UM.Settings.SettingInstance import InstanceState
from UM.Settings.SettingFunction import SettingFunction

from .ExtruderManager import ExtruderManager

##  Cura-specific SettingPropertyProvider subclass that adds some Cura-related functionality.
#
#   This subclass automatically determines the container stack it should use based on the
#   criteria specified by Cura. Additionally, it provides two properties, one for showing
#   the revert button and one for showing the inheritance warning button.
class CuraPropertyProvider(SettingPropertyProvider):
    def __init__(self, parent = None):
        super().__init__(parent = parent)

        self._global_container_stack = None
        self._active_container_stack = None
        self._should_show_inherit = False

        Application.getInstance().globalContainerStackChanged.connect(self._updateStack)
        ExtruderManager.getInstance().activeExtruderChanged.connect(self._updateStack)
        self.keyChanged.connect(self._updateStack)
        self.stackLevelChanged.connect(self.shouldShowRevertChanged)

    shouldShowRevertChanged = pyqtSignal()
    ##  Whether the revert button should be visible
    @pyqtProperty(bool, notify = shouldShowRevertChanged)
    def shouldShowRevert(self):
        return 0 in self.stackLevels

    shouldShowInheritChanged = pyqtSignal()
    ##  Whether the inherit button should be visible
    @pyqtProperty(bool, notify = shouldShowInheritChanged)
    def shouldShowInherit(self):
        return self._should_show_inherit

    # protected:

    # Figure out which container stack to use, based on extruder count and other properties
    def _updateStack(self):
        if not self._key:
            return

        global_container_stack = Application.getInstance().getGlobalContainerStack()
        if not global_container_stack:
            return

        if global_container_stack != self._global_container_stack:
            if self._global_container_stack:
                self._global_container_stack.propertiesChanged.disconnect(self._onLimitToExtruderChanged)
            self._global_container_stack = global_container_stack
            self._global_container_stack.propertiesChanged.connect(self._onLimitToExtruderChanged)

        if global_container_stack.getProperty("machine_extruder_count", "value") <= 1:
            # Simple case: Only one extruder
            self.setContainerStackId("global")
            return

        settable_per_extruder = global_container_stack.getProperty(self._key, "settable_per_extruder")
        if not settable_per_extruder:
            # Another simple case: if the setting is not settable per extruder, use the global stack
            self.setContainerStackId("global")
            return

        limit_to_extruder = global_container_stack.getProperty(self._key, "limit_to_extruder")
        if limit_to_extruder is not None and int(limit_to_extruder) >= 0:
            # Limit to extruder is set, so use the specified extruder
            extruder_stack = ExtruderManager.getInstance().getExtruderStack(limit_to_extruder)
            if extruder_stack:
                self.setContainerStackId(extruder_stack.getId())
            else:
                Logger.log("w", "Setting {key} indicates it should be limited to extruder {extruder} but that extruder was not found!", key = self._key, extruder = limit_to_extruder)
            return

        self.setContainerStackId(ExtruderManager.getInstance().activeExtruderStackId)
        self._updateShouldShowInherit()

    # The used stack should be changed when limit_to_extruder changes
    def _onLimitToExtruderChanged(self, key, property_names):
        if key != self._key:
            return

        if "limit_to_extruder" in property_names:
            self._updateStack()

        if "value" in property_names:
            self._updateShouldShowInherit()

    # Overridden from SettingPropertyProvider
    #
    # Ensures we also update the shouldShowInherit property
    def _onPropertiesChanged(self, key, property_names):
        super()._onPropertiesChanged(key, property_names)
        self._updateShouldShowInherit()

    # Update the shouldShowInherit property
    def _updateShouldShowInherit(self):
        should_show_inherit = self._determineInherit()

        if should_show_inherit != self._should_show_inherit:
            self._should_show_inherit = should_show_inherit
            self.shouldShowInheritChanged.emit()

    def _determineInherit(self):
        if self._stack.getProperty(self._key, "resolve") != None:
            return False

        if self._stack.getProperty(self._key, "state") != InstanceState.User:
            return False

        if not self._stack.getProperty(self._key, "enabled"):
            return False

        if isinstance(self._stack.getTop().getProperty(self._key, "value"), SettingFunction):
            return False

        containers = []
        stack = self._stack
        while stack:
            containers.extend(stack.getContainers())
            stack = stack.getNextStack()

        has_setting_function = False
        has_non_function_value = False
        for container in containers:
            try:
                value = container.getProperty(self._key, "value")
            except AttributeError:
                continue

            if value is not None:
                # If a setting doesn't use any keys, it won't change it's value, so treat it as if it's a fixed value
                has_setting_function = isinstance(value, SettingFunction)
                if has_setting_function:
                    for setting_key in value.getUsedSettingKeys():
                        if setting_key in self._stack.getAllKeys():
                            break # We found an actual setting. So has_setting_function can remain true
                    else:
                        # All of the setting_keys turned out to not be setting keys at all!
                        # This can happen due enum keys also being marked as settings.
                        has_setting_function = False

                if has_setting_function is False:
                    has_non_function_value = True
                    continue

            if has_setting_function:
                break  # There is a setting function somewhere, stop looking deeper.

        return has_setting_function and has_non_function_value
