from pathlib import Path
from typing import Dict, List, Optional, Union

from RPA.core.windows.elements import StructureType
from RPA.core.windows.helpers import IS_WINDOWS
from RPA.core.windows.locators import MatchObject, WindowsElement
from RPA.core.windows.window import WindowMethods

if IS_WINDOWS:
    import uiautomation as auto
    from uiautomation import Control


RecordElement = Dict[str, Optional[Union[float, str, "Control", List[str]]]]

NOT_AVAILABLE = "N/A"


class ElementInspector:
    """Element locator inspector"""

    MATCH_PRIORITY = ["automation_id", "name"]  # element matching priority

    def __init__(self, max_depth: int = 8):
        self._max_depth = max_depth
        # Lazily loaded with verbose mode on for printing the tree and returning the
        #  structure.
        self._windows_elements: Optional["WindowsElements"] = None

    @property
    def windows_elements(self) -> "WindowsElements":
        """The minimal core flavor of the Windows library."""
        if not self._windows_elements:
            from RPA.core.windows import WindowsElements

            self._windows_elements = WindowsElements()
        return self._windows_elements

    def inspect_element(
        self,
        recording: List[RecordElement],
        verbose: bool = False,
    ) -> None:
        """Inspect Windows element under mouse pointer.

        :param recording: Store the dict records under this list.
        :param verbose: Show exhaustive locators if `True`, otherwise just simple ones.
            Switching this on will make recording slower as it is refreshing the
            element tree with each click in order to provide their path strategy as
            well.
        """
        # TODO(cmin764): Support Python syntax as well. (currently just RF keywords)
        with auto.UIAutomationInitializerInThread(debug=False):
            control = auto.ControlFromCursor()
            parent_control = control.GetParentControl()
            exec_path = ""
            try:
                top_level_control = control.GetTopLevelControl()
            except AttributeError:
                top_level_control = None
                top_level_handle = NOT_AVAILABLE
            else:
                top_level_handle = top_level_control.NativeWindowHandle
                try:
                    exec_path = WindowMethods.get_fullpath(top_level_control.ProcessId)
                except Exception:  # pylint: disable=broad-except
                    pass

            top_properties = self._get_element_key_properties(
                top_level_control, verbose=verbose
            )
            parent_properties = self._get_element_key_properties(
                parent_control, verbose=verbose
            )
            child_properties = self._get_element_key_properties(
                control, top_level_control=top_level_control, verbose=verbose
            )

            top_locator = " and ".join(top_properties) or NOT_AVAILABLE
            parent_locator = " and ".join(parent_properties) or NOT_AVAILABLE
            child_locator = " and ".join(child_properties) or NOT_AVAILABLE
            control_locator = child_locator
            if parent_locator != NOT_AVAILABLE and not (
                "name:" in child_locator or "id:" in child_locator
            ):
                control_locator = f"{parent_locator} > {child_locator}"

            recording.append(
                {
                    "type": "locator",
                    "exec_path": exec_path,
                    "exec": Path(exec_path).name,
                    "top": top_locator,
                    "top_handle": top_level_handle,
                    "x": top_level_control,
                    "locator": control_locator,
                    "top_props": top_properties,
                    "parent_props": parent_properties,
                    "props": child_properties,
                    "name": parent_control.Name if parent_control else None,
                    "control": parent_control,
                }
            )

    @classmethod
    def _filter_structure(
        cls,
        structure: StructureType,
        *,
        control: "Control",
        control_type: str,
        class_name: str,
        **kwargs,
    ) -> Dict[str, List[WindowsElement]]:
        elements: Dict[str, List[WindowsElement]] = {}

        at_level = 0
        cursor = control
        while not cursor.IsTopLevel():
            cursor = cursor.GetParentControl()
            at_level += 1

        for element in structure[at_level]:
            not_good = (
                control_type
                and control_type != element.control_type
                or class_name
                and class_name != element.class_name
            )
            if not_good:
                continue

            for attr in cls.MATCH_PRIORITY:
                value = kwargs[attr]
                if value and value == getattr(element, attr):
                    elements.setdefault(attr, []).append(element)

        return elements

    def _match_element_for_path(
        self, control: "Control", top_level_control: "Control", **kwargs
    ) -> Optional[str]:
        # Obtain a new element tree structure during every click, as the tree changes
        #  (expands/shrinks/rotates) with element actions producing UI display changes.
        top_level_element = WindowsElement(top_level_control, None)
        structure = self.windows_elements.print_tree(
            top_level_element,
            return_structure=True,
            log_as_warnings=None,
            max_depth=self._max_depth,
        )
        elems_dict = self._filter_structure(structure, control=control, **kwargs)

        for prio in self.MATCH_PRIORITY:
            elems = elems_dict.get(prio, [])
            for candidate in elems:
                maybe_path = candidate.locator.rsplit(MatchObject.TREE_SEP, 1)[-1]
                if "path:" in maybe_path:
                    return maybe_path

        return None

    def _get_element_key_properties(
        self,
        control: Optional["Control"],
        *,
        top_level_control: Optional["Control"] = None,
        verbose: bool,
        regex_limit: int = 300,
    ) -> List[str]:
        if not control:
            print("Got null control!")
            return []

        display_name = name = control.Name
        automation_id = control.AutomationId
        control_type = control.ControlTypeName
        class_name = control.ClassName
        locators = []
        if len(display_name) > 0:
            name_property = "name:"
            if len(display_name) > regex_limit:
                name_property = "regex:"
                display_name = display_name[:regex_limit].strip()
            if " " in display_name:
                q = MatchObject.QUOTE
                display_name = f"{q}{display_name}{q}"
            locators.append(f"{name_property}{display_name}")
        # NOTE(cmin764): Sometimes, the automation ID is a randomly generated number,
        #  different with each run. (therefore you can't rely on it in the locator)
        if automation_id and not str(automation_id).isnumeric():
            locators.append(f"id:{automation_id}")
        if len(control_type) > 0:
            locators.append(f"type:{control_type}")
        if len(class_name) > 0:
            locators.append(f"class:{class_name}")

        # Add the `path:` strategy as well with verbose recordings. (useful when you
        #  can't rely on Automation IDs nor names)
        if verbose and top_level_control:
            path = self._match_element_for_path(
                control,
                top_level_control,
                control_type=control_type,
                class_name=class_name,
                automation_id=automation_id,
                name=name,
            )
            if path:
                locators.append(path)

        if locators:
            if not verbose:
                locators = locators[:1]
            return locators

        print("Was unable to construct locator for the control!")
        return []
