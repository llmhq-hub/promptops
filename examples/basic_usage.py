#!/usr/bin/env python3
"""
Basic Usage Examples for llmhq-promptops

This script demonstrates the core functionality of the llmhq-promptops SDK
including prompt resolution, version references, and basic testing.
"""

from llmhq_promptops import get_prompt, PromptManager
from llmhq_promptops.core.template import PromptTemplate
from pathlib import Path


def example_basic_prompt_resolution():
    """Demonstrate basic prompt resolution with different version references."""
    print("🔍 Basic Prompt Resolution Examples")
    print("=" * 50)
    
    try:
        # Smart default - uses unstaged if different from working, else working
        prompt1 = get_prompt("welcome-message", {"user_name": "Alice", "plan": "Pro"})
        print(f"Smart default: {prompt1[:100]}...")
        
        # Specific version references
        prompt2 = get_prompt("welcome-message:working", {"user_name": "Bob"})
        print(f"Working version: {prompt2[:100]}...")
        
        # Test uncommitted changes
        prompt3 = get_prompt("welcome-message:unstaged", {"user_name": "Charlie"})
        print(f"Unstaged version: {prompt3[:100]}...")
        
    except Exception as e:
        print(f"⚠️  Example requires existing prompts: {e}")
        print("💡 Run 'promptops init repo' and 'promptops create prompt welcome-message' first")


def example_prompt_manager():
    """Demonstrate advanced PromptManager functionality."""
    print("\n🔧 PromptManager Advanced Usage")
    print("=" * 50)
    
    try:
        manager = PromptManager()
        
        # Check for uncommitted changes
        prompt_id = "welcome-message"
        has_changes = manager.has_uncommitted_changes(prompt_id)
        print(f"📝 {prompt_id} has uncommitted changes: {has_changes}")
        
        # Get prompt metadata without rendering
        template = manager._get_template_cached(f"{prompt_id}:working")
        print(f"📋 Template metadata: {template.metadata}")
        print(f"🔧 Required variables: {list(template.required_variables)}")
        
        # Get prompt differences
        diff = manager.get_prompt_diff(prompt_id, "working", "unstaged")
        if diff.strip():
            print(f"📊 Differences found:\n{diff}")
        else:
            print("✅ No differences between working and unstaged versions")
            
    except Exception as e:
        print(f"⚠️  Error: {e}")


def example_version_management():
    """Demonstrate version management and status checking."""
    print("\n📋 Version Management Examples")
    print("=" * 50)
    
    try:
        manager = PromptManager()
        
        # List all prompt statuses
        promptops_dir = Path(".promptops/prompts")
        if promptops_dir.exists():
            prompt_files = list(promptops_dir.glob("*.yaml"))
            print(f"📁 Found {len(prompt_files)} prompt files:")
            
            for prompt_file in prompt_files[:3]:  # Show first 3
                prompt_id = prompt_file.stem
                try:
                    has_changes = manager.has_uncommitted_changes(prompt_id)
                    status = "🔄 Modified" if has_changes else "✅ Up to date"
                    print(f"   {prompt_id}: {status}")
                except:
                    print(f"   {prompt_id}: ❓ Status unknown")
        else:
            print("📁 No .promptops directory found")
            
    except Exception as e:
        print(f"⚠️  Error: {e}")


def example_template_rendering():
    """Demonstrate template rendering with variable validation."""
    print("\n🎨 Template Rendering Examples")
    print("=" * 50)
    
    # Example YAML content
    yaml_content = """
metadata:
  id: example-prompt
  version: "1.0.0"
  description: "Example prompt for demonstration"

template: |
  Hello {{ user_name }}!
  {% if plan %}
  You are subscribed to the {{ plan }} plan.
  {% endif %}
  
  Available features:
  {% for feature in features %}
  - {{ feature }}
  {% endfor %}

variables:
  user_name: {type: string, required: true}
  plan: {type: string, required: false}
  features: {type: list, default: ["Basic Feature"]}
"""
    
    try:
        # Create template from YAML
        template = PromptTemplate(yaml_content)
        print(f"📋 Template ID: {template.metadata['id']}")
        print(f"📋 Required variables: {list(template.required_variables)}")
        
        # Render with different variable sets
        result1 = template.render({"user_name": "Alice"})
        print(f"🎨 Minimal variables:\n{result1}")
        
        result2 = template.render({
            "user_name": "Bob", 
            "plan": "Enterprise",
            "features": ["Advanced Analytics", "Custom Integrations", "Priority Support"]
        })
        print(f"🎨 Full variables:\n{result2}")
        
        # Demonstrate validation
        try:
            template.render({})  # Missing required variable
        except ValueError as e:
            print(f"✅ Validation works: {e}")
            
    except Exception as e:
        print(f"⚠️  Error: {e}")


def example_error_handling():
    """Demonstrate proper error handling patterns."""
    print("\n⚠️  Error Handling Examples")
    print("=" * 50)
    
    # Non-existent prompt
    try:
        get_prompt("non-existent-prompt")
    except Exception as e:
        print(f"✅ Non-existent prompt: {type(e).__name__}: {e}")
    
    # Missing required variables
    try:
        get_prompt("welcome-message", {})  # Assuming it requires variables
    except Exception as e:
        print(f"✅ Missing variables: {type(e).__name__}: {e}")
    
    # Invalid version reference
    try:
        get_prompt("welcome-message:invalid-version")
    except Exception as e:
        print(f"✅ Invalid version: {type(e).__name__}: {e}")


def main():
    """Run all examples."""
    print("🚀 llmhq-promptops SDK Examples")
    print("=" * 50)
    print("This script demonstrates core SDK functionality.")
    print("For best results, run in a directory with .promptops/ setup.\n")
    
    example_basic_prompt_resolution()
    example_prompt_manager()
    example_version_management()
    example_template_rendering()
    example_error_handling()
    
    print("\n✨ Examples completed!")
    print("💡 Try creating prompts with: promptops create prompt your-prompt-name")
    print("📚 See README.md for more detailed documentation")


if __name__ == "__main__":
    main()