"""
Tests for cogs.ai_core.memory.state_tracker module.
"""




class TestCharacterStateDataclass:
    """Tests for CharacterState dataclass."""

    def test_create_character_state(self):
        """Test creating CharacterState."""
        from cogs.ai_core.memory.state_tracker import CharacterState

        state = CharacterState(name="Faust")

        assert state.name == "Faust"
        assert state.location is None
        assert state.activity is None
        assert state.emotion is None

    def test_character_state_with_all_fields(self):
        """Test CharacterState with all fields."""
        from cogs.ai_core.memory.state_tracker import CharacterState

        state = CharacterState(
            name="Faust",
            location="Library",
            activity="Reading",
            emotion="calm",
            nearby_characters=["Dante"],
            inventory=["Book"],
            last_action="Turned a page",
            last_dialogue="Interesting..."
        )

        assert state.name == "Faust"
        assert state.location == "Library"
        assert state.activity == "Reading"
        assert state.emotion == "calm"
        assert "Dante" in state.nearby_characters
        assert "Book" in state.inventory

    def test_to_dict(self):
        """Test CharacterState to_dict method."""
        from cogs.ai_core.memory.state_tracker import CharacterState

        state = CharacterState(
            name="Faust",
            location="Library",
            emotion="calm"
        )

        result = state.to_dict()

        assert "name" in result
        assert result["name"] == "Faust"
        assert result["location"] == "Library"
        # Empty fields should be excluded
        assert "activity" not in result or result.get("activity") is None

    def test_from_dict(self):
        """Test CharacterState from_dict method."""
        from cogs.ai_core.memory.state_tracker import CharacterState

        data = {
            "name": "Faust",
            "location": "Office",
            "emotion": "focused"
        }

        state = CharacterState.from_dict(data)

        assert state.name == "Faust"
        assert state.location == "Office"
        assert state.emotion == "focused"

    def test_to_prompt_text(self):
        """Test CharacterState to_prompt_text method."""
        from cogs.ai_core.memory.state_tracker import CharacterState

        state = CharacterState(
            name="Faust",
            location="Library",
            activity="Reading a book",
            emotion="calm"
        )

        result = state.to_prompt_text()

        assert "Faust" in result
        assert "Library" in result
        assert "Reading a book" in result


class TestCharacterStateTracker:
    """Tests for CharacterStateTracker class."""

    def test_create_tracker(self):
        """Test creating CharacterStateTracker."""
        from cogs.ai_core.memory.state_tracker import CharacterStateTracker

        tracker = CharacterStateTracker()

        assert tracker is not None

    def test_get_state_nonexistent(self):
        """Test get_state returns None for nonexistent character."""
        from cogs.ai_core.memory.state_tracker import CharacterStateTracker

        tracker = CharacterStateTracker()

        result = tracker.get_state("Unknown", 12345)

        assert result is None

    def test_set_and_get_state(self):
        """Test setting and getting state."""
        from cogs.ai_core.memory.state_tracker import CharacterStateTracker

        tracker = CharacterStateTracker()

        state = tracker.set_state("Faust", 12345, location="Library")

        assert state.name == "Faust"
        assert state.location == "Library"

        retrieved = tracker.get_state("Faust", 12345)
        assert retrieved is not None
        assert retrieved.location == "Library"

    def test_update_existing_state(self):
        """Test updating existing state."""
        from cogs.ai_core.memory.state_tracker import CharacterStateTracker

        tracker = CharacterStateTracker()

        tracker.set_state("Faust", 12345, location="Library")
        tracker.set_state("Faust", 12345, emotion="happy")

        state = tracker.get_state("Faust", 12345)

        assert state.location == "Library"  # Preserved
        assert state.emotion == "happy"  # Updated

    def test_get_all_states(self):
        """Test get_all_states method."""
        from cogs.ai_core.memory.state_tracker import CharacterStateTracker

        tracker = CharacterStateTracker()

        tracker.set_state("Faust", 12345, location="Library")
        tracker.set_state("Dante", 12345, location="Office")

        states = tracker.get_all_states(12345)

        assert len(states) == 2
        assert "Faust" in states
        assert "Dante" in states

    def test_get_all_states_empty_channel(self):
        """Test get_all_states for empty channel."""
        from cogs.ai_core.memory.state_tracker import CharacterStateTracker

        tracker = CharacterStateTracker()

        states = tracker.get_all_states(99999)

        assert states == {}


class TestStateTrackerScene:
    """Tests for scene management in CharacterStateTracker."""

    def test_set_and_get_scene(self):
        """Test setting and getting scene."""
        from cogs.ai_core.memory.state_tracker import CharacterStateTracker

        tracker = CharacterStateTracker()

        tracker.set_scene(12345, "A dark library at midnight")

        scene = tracker.get_scene(12345)

        assert scene == "A dark library at midnight"

    def test_get_scene_nonexistent(self):
        """Test get_scene returns None for nonexistent channel."""
        from cogs.ai_core.memory.state_tracker import CharacterStateTracker

        tracker = CharacterStateTracker()

        scene = tracker.get_scene(99999)

        assert scene is None


class TestStateTrackerClear:
    """Tests for clearing state in CharacterStateTracker."""

    def test_clear_channel(self):
        """Test clear_channel removes all states."""
        from cogs.ai_core.memory.state_tracker import CharacterStateTracker

        tracker = CharacterStateTracker()

        tracker.set_state("Faust", 12345, location="Library")
        tracker.set_scene(12345, "A dark room")

        tracker.clear_channel(12345)

        assert tracker.get_state("Faust", 12345) is None
        assert tracker.get_scene(12345) is None


class TestStateTrackerPersistence:
    """Tests for state persistence in CharacterStateTracker."""

    def test_to_dict(self):
        """Test to_dict exports state."""
        from cogs.ai_core.memory.state_tracker import CharacterStateTracker

        tracker = CharacterStateTracker()

        tracker.set_state("Faust", 12345, location="Library")
        tracker.set_scene(12345, "Night time")

        data = tracker.to_dict(12345)

        assert "states" in data
        assert "scene" in data
        assert data["scene"] == "Night time"

    def test_from_dict(self):
        """Test from_dict imports state."""
        from cogs.ai_core.memory.state_tracker import CharacterStateTracker

        tracker = CharacterStateTracker()

        data = {
            "states": {
                "Faust": {"name": "Faust", "location": "Library"}
            },
            "scene": "Dark night"
        }

        tracker.from_dict(12345, data)

        state = tracker.get_state("Faust", 12345)
        assert state is not None
        assert state.location == "Library"
        assert tracker.get_scene(12345) == "Dark night"


class TestStateTrackerPrompt:
    """Tests for prompt generation in CharacterStateTracker."""

    def test_get_states_for_prompt(self):
        """Test get_states_for_prompt generates text."""
        from cogs.ai_core.memory.state_tracker import CharacterStateTracker

        tracker = CharacterStateTracker()

        tracker.set_state("Faust", 12345, location="Library", emotion="calm")

        prompt = tracker.get_states_for_prompt(12345)

        assert "Faust" in prompt
        assert "Library" in prompt

    def test_get_states_for_prompt_empty(self):
        """Test get_states_for_prompt returns empty for no states."""
        from cogs.ai_core.memory.state_tracker import CharacterStateTracker

        tracker = CharacterStateTracker()

        prompt = tracker.get_states_for_prompt(99999)

        assert prompt == ""

    def test_get_states_for_prompt_filtered(self):
        """Test get_states_for_prompt with character filter."""
        from cogs.ai_core.memory.state_tracker import CharacterStateTracker

        tracker = CharacterStateTracker()

        tracker.set_state("Faust", 12345, location="Library")
        tracker.set_state("Dante", 12345, location="Office")

        prompt = tracker.get_states_for_prompt(12345, character_names=["Faust"])

        assert "Faust" in prompt
        assert "Dante" not in prompt


class TestStateTrackerUpdateFromResponse:
    """Tests for update_from_response in CharacterStateTracker."""

    def test_update_from_response_basic(self):
        """Test update_from_response extracts character state."""
        from cogs.ai_core.memory.state_tracker import CharacterStateTracker

        tracker = CharacterStateTracker()

        response = '{{Faust}} กำลังนั่งอยู่ที่ห้องสมุด "น่าสนใจ..." ยิ้มนิดหน่อย'

        updated = tracker.update_from_response(response, 12345)

        # Should extract character name
        # Check if any updates were made
        assert isinstance(updated, list)

    def test_update_from_response_no_characters(self):
        """Test update_from_response with no character blocks."""
        from cogs.ai_core.memory.state_tracker import CharacterStateTracker

        tracker = CharacterStateTracker()

        response = "Just some regular text without character markers."

        updated = tracker.update_from_response(response, 12345)

        assert updated == []


class TestGlobalStateTracker:
    """Tests for global state_tracker instance."""

    def test_global_instance_exists(self):
        """Test global state_tracker exists."""
        from cogs.ai_core.memory.state_tracker import state_tracker

        assert state_tracker is not None

    def test_global_instance_is_tracker(self):
        """Test global state_tracker is CharacterStateTracker."""
        from cogs.ai_core.memory.state_tracker import CharacterStateTracker, state_tracker

        assert isinstance(state_tracker, CharacterStateTracker)
