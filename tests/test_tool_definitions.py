"""Tests for tool_definitions module."""

import pytest


class TestGetToolDefinitions:
    """Tests for get_tool_definitions function."""

    def test_returns_list(self):
        """Test that function returns a list."""
        from cogs.ai_core.tools.tool_definitions import get_tool_definitions
        
        result = get_tool_definitions()
        assert isinstance(result, list)

    def test_returns_non_empty(self):
        """Test that function returns non-empty list."""
        from cogs.ai_core.tools.tool_definitions import get_tool_definitions
        
        result = get_tool_definitions()
        assert len(result) > 0

    def test_first_item_has_function_declarations(self):
        """Test that first item has function_declarations key."""
        from cogs.ai_core.tools.tool_definitions import get_tool_definitions
        
        result = get_tool_definitions()
        assert "function_declarations" in result[0]

    def test_function_declarations_is_list(self):
        """Test that function_declarations is a list."""
        from cogs.ai_core.tools.tool_definitions import get_tool_definitions
        
        result = get_tool_definitions()
        assert isinstance(result[0]["function_declarations"], list)


class TestToolDeclarationStructure:
    """Tests for individual tool declaration structure."""

    def test_all_declarations_have_name(self):
        """Test all function declarations have a name."""
        from cogs.ai_core.tools.tool_definitions import get_tool_definitions
        
        result = get_tool_definitions()
        declarations = result[0]["function_declarations"]
        
        for decl in declarations:
            assert "name" in decl
            assert isinstance(decl["name"], str)
            assert len(decl["name"]) > 0

    def test_all_declarations_have_description(self):
        """Test all function declarations have a description."""
        from cogs.ai_core.tools.tool_definitions import get_tool_definitions
        
        result = get_tool_definitions()
        declarations = result[0]["function_declarations"]
        
        for decl in declarations:
            assert "description" in decl
            assert isinstance(decl["description"], str)

    def test_all_declarations_have_parameters(self):
        """Test all function declarations have parameters."""
        from cogs.ai_core.tools.tool_definitions import get_tool_definitions
        
        result = get_tool_definitions()
        declarations = result[0]["function_declarations"]
        
        for decl in declarations:
            assert "parameters" in decl
            assert isinstance(decl["parameters"], dict)


class TestSpecificTools:
    """Tests for specific tool definitions."""

    def test_create_text_channel_exists(self):
        """Test create_text_channel tool exists."""
        from cogs.ai_core.tools.tool_definitions import get_tool_definitions
        
        result = get_tool_definitions()
        declarations = result[0]["function_declarations"]
        names = [d["name"] for d in declarations]
        
        assert "create_text_channel" in names

    def test_create_text_channel_has_name_param(self):
        """Test create_text_channel has name parameter."""
        from cogs.ai_core.tools.tool_definitions import get_tool_definitions
        
        result = get_tool_definitions()
        declarations = result[0]["function_declarations"]
        tool = next(d for d in declarations if d["name"] == "create_text_channel")
        
        assert "name" in tool["parameters"]["properties"]
        assert "name" in tool["parameters"]["required"]

    def test_create_voice_channel_exists(self):
        """Test create_voice_channel tool exists."""
        from cogs.ai_core.tools.tool_definitions import get_tool_definitions
        
        result = get_tool_definitions()
        declarations = result[0]["function_declarations"]
        names = [d["name"] for d in declarations]
        
        assert "create_voice_channel" in names

    def test_create_category_exists(self):
        """Test create_category tool exists."""
        from cogs.ai_core.tools.tool_definitions import get_tool_definitions
        
        result = get_tool_definitions()
        declarations = result[0]["function_declarations"]
        names = [d["name"] for d in declarations]
        
        assert "create_category" in names

    def test_delete_channel_exists(self):
        """Test delete_channel tool exists."""
        from cogs.ai_core.tools.tool_definitions import get_tool_definitions
        
        result = get_tool_definitions()
        declarations = result[0]["function_declarations"]
        names = [d["name"] for d in declarations]
        
        assert "delete_channel" in names

    def test_create_role_exists(self):
        """Test create_role tool exists."""
        from cogs.ai_core.tools.tool_definitions import get_tool_definitions
        
        result = get_tool_definitions()
        declarations = result[0]["function_declarations"]
        names = [d["name"] for d in declarations]
        
        assert "create_role" in names

    def test_delete_role_exists(self):
        """Test delete_role tool exists."""
        from cogs.ai_core.tools.tool_definitions import get_tool_definitions
        
        result = get_tool_definitions()
        declarations = result[0]["function_declarations"]
        names = [d["name"] for d in declarations]
        
        assert "delete_role" in names

    def test_add_role_exists(self):
        """Test add_role tool exists."""
        from cogs.ai_core.tools.tool_definitions import get_tool_definitions
        
        result = get_tool_definitions()
        declarations = result[0]["function_declarations"]
        names = [d["name"] for d in declarations]
        
        assert "add_role" in names

    def test_remove_role_exists(self):
        """Test remove_role tool exists."""
        from cogs.ai_core.tools.tool_definitions import get_tool_definitions
        
        result = get_tool_definitions()
        declarations = result[0]["function_declarations"]
        names = [d["name"] for d in declarations]
        
        assert "remove_role" in names

    def test_list_channels_exists(self):
        """Test list_channels tool exists."""
        from cogs.ai_core.tools.tool_definitions import get_tool_definitions
        
        result = get_tool_definitions()
        declarations = result[0]["function_declarations"]
        names = [d["name"] for d in declarations]
        
        assert "list_channels" in names

    def test_list_roles_exists(self):
        """Test list_roles tool exists."""
        from cogs.ai_core.tools.tool_definitions import get_tool_definitions
        
        result = get_tool_definitions()
        declarations = result[0]["function_declarations"]
        names = [d["name"] for d in declarations]
        
        assert "list_roles" in names

    def test_list_members_exists(self):
        """Test list_members tool exists."""
        from cogs.ai_core.tools.tool_definitions import get_tool_definitions
        
        result = get_tool_definitions()
        declarations = result[0]["function_declarations"]
        names = [d["name"] for d in declarations]
        
        assert "list_members" in names

    def test_get_user_info_exists(self):
        """Test get_user_info tool exists."""
        from cogs.ai_core.tools.tool_definitions import get_tool_definitions
        
        result = get_tool_definitions()
        declarations = result[0]["function_declarations"]
        names = [d["name"] for d in declarations]
        
        assert "get_user_info" in names

    def test_read_channel_exists(self):
        """Test read_channel tool exists."""
        from cogs.ai_core.tools.tool_definitions import get_tool_definitions
        
        result = get_tool_definitions()
        declarations = result[0]["function_declarations"]
        names = [d["name"] for d in declarations]
        
        assert "read_channel" in names

    def test_remember_tool_exists(self):
        """Test remember tool exists."""
        from cogs.ai_core.tools.tool_definitions import get_tool_definitions
        
        result = get_tool_definitions()
        declarations = result[0]["function_declarations"]
        names = [d["name"] for d in declarations]
        
        assert "remember" in names

    def test_set_channel_permission_exists(self):
        """Test set_channel_permission tool exists."""
        from cogs.ai_core.tools.tool_definitions import get_tool_definitions
        
        result = get_tool_definitions()
        declarations = result[0]["function_declarations"]
        names = [d["name"] for d in declarations]
        
        assert "set_channel_permission" in names

    def test_set_role_permission_exists(self):
        """Test set_role_permission tool exists."""
        from cogs.ai_core.tools.tool_definitions import get_tool_definitions
        
        result = get_tool_definitions()
        declarations = result[0]["function_declarations"]
        names = [d["name"] for d in declarations]
        
        assert "set_role_permission" in names


class TestParameterTypes:
    """Tests for parameter type definitions."""

    def test_create_role_color_hex_param(self):
        """Test create_role has color_hex parameter."""
        from cogs.ai_core.tools.tool_definitions import get_tool_definitions
        
        result = get_tool_definitions()
        declarations = result[0]["function_declarations"]
        tool = next(d for d in declarations if d["name"] == "create_role")
        
        assert "color_hex" in tool["parameters"]["properties"]
        assert tool["parameters"]["properties"]["color_hex"]["type"] == "STRING"

    def test_list_members_limit_param(self):
        """Test list_members has limit parameter."""
        from cogs.ai_core.tools.tool_definitions import get_tool_definitions
        
        result = get_tool_definitions()
        declarations = result[0]["function_declarations"]
        tool = next(d for d in declarations if d["name"] == "list_members")
        
        assert "limit" in tool["parameters"]["properties"]
        assert tool["parameters"]["properties"]["limit"]["type"] == "INTEGER"

    def test_set_channel_permission_value_param(self):
        """Test set_channel_permission has value boolean parameter."""
        from cogs.ai_core.tools.tool_definitions import get_tool_definitions
        
        result = get_tool_definitions()
        declarations = result[0]["function_declarations"]
        tool = next(d for d in declarations if d["name"] == "set_channel_permission")
        
        assert "value" in tool["parameters"]["properties"]
        assert tool["parameters"]["properties"]["value"]["type"] == "BOOLEAN"


class TestBackwardCompatibility:
    """Tests for backward compatibility re-exports."""

    def test_import_from_tools_module(self):
        """Test import from tools module."""
        from cogs.ai_core.tools.tool_definitions import get_tool_definitions
        
        result = get_tool_definitions()
        assert isinstance(result, list)

    def test_tools_module_all_exports(self):
        """Test __all__ exports."""
        from cogs.ai_core.tools import tool_definitions
        
        assert "get_tool_definitions" in tool_definitions.__all__


class TestToolCount:
    """Tests for tool count."""

    def test_minimum_tool_count(self):
        """Test that there are minimum expected tools."""
        from cogs.ai_core.tools.tool_definitions import get_tool_definitions
        
        result = get_tool_definitions()
        declarations = result[0]["function_declarations"]
        
        # We expect at least 15 tools
        assert len(declarations) >= 15

    def test_unique_tool_names(self):
        """Test all tool names are unique."""
        from cogs.ai_core.tools.tool_definitions import get_tool_definitions
        
        result = get_tool_definitions()
        declarations = result[0]["function_declarations"]
        names = [d["name"] for d in declarations]
        
        assert len(names) == len(set(names))
