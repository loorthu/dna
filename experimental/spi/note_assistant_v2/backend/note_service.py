import os
import random
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter()

class LLMSummaryRequest(BaseModel):
    text: str

# --- LLM IMPLEMENTATION CODE ---

import os
import yaml
import requests
from openai import OpenAI
import anthropic
import google.generativeai as genai
import re
from dotenv import load_dotenv

# === CONFIGURATION LOADING ===
def load_llm_config():
    """Load LLM configuration from YAML file. Checks for user config first, falls back to factory defaults."""
    base_dir = os.path.dirname(__file__)
    user_config_path = os.path.join(base_dir, 'llm_config.yaml')
    factory_config_path = os.path.join(base_dir, 'llm_config.factory.yaml')
    
    # Try to load user configuration first
    if os.path.exists(user_config_path):
        print(f"Loading user LLM configuration from: {user_config_path}")
        with open(user_config_path, 'r') as f:
            return yaml.safe_load(f)
    
    # Fall back to factory configuration
    print(f"Loading factory LLM configuration from: {factory_config_path}")
    with open(factory_config_path, 'r') as f:
        return yaml.safe_load(f)

def get_model_config(provider, model=None, config=None):
    """Get configuration for a specific provider/model, merging defaults with model-specific overrides."""
    if config is None:
        config = LLM_CONFIG
    
    # Start with default configuration
    merged_config = config['default'].copy()
    
    # Apply model-specific overrides if specified
    if model and 'model_overrides' in config and model in config['model_overrides']:
        merged_config.update(config['model_overrides'][model])
    
    return merged_config



def get_available_models(config=None):
    """Get list of all available models with their display information."""
    if config is None:
        config = LLM_CONFIG
    
    if 'models' in config['default']:
        return config['default']['models']
    
    return []

def get_enabled_providers():
    """Get list of enabled LLM providers based on environment variables."""
    enabled = []
    if os.getenv('ENABLE_OPENAI', 'false').lower() in ('1', 'true', 'yes'):
        enabled.append('openai')
    if os.getenv('ENABLE_ANTHROPIC', 'false').lower() in ('1', 'true', 'yes'):
        enabled.append('claude')
    if os.getenv('ENABLE_OLLAMA', 'false').lower() in ('1', 'true', 'yes'):
        enabled.append('ollama')
    if os.getenv('ENABLE_GOOGLE', 'false').lower() in ('1', 'true', 'yes'):
        enabled.append('gemini')
    return enabled

def get_available_models_for_enabled_providers():
    """Get models that are available for enabled providers."""
    enabled_providers = get_enabled_providers()
    available_models = []
    
    if 'models' in LLM_CONFIG['default']:
        for model in LLM_CONFIG['default']['models']:
            if model['provider'] in enabled_providers:
                available_models.append(model)
    
    return available_models

def get_model_for_provider(provider):
    """Get the model name for a specific provider from configuration."""
    for model in LLM_CONFIG['default']['models']:
        if model['provider'] == provider:
            return model['model_name']
    return None

# Load configuration
LLM_CONFIG = load_llm_config()

def summarize_openai(conversation, model, client, config):
    prompt = config['user_prompt_template'].format(conversation=conversation)
    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": config['system_prompt']},
            {"role": "user", "content": prompt}
        ],
        temperature=config['temperature'],
    )
    return response.choices[0].message.content

def summarize_claude(conversation, model, client, config):
    prompt = config['user_prompt_template'].format(conversation=conversation)
    response = client.messages.create(
        model=model,
        max_tokens=config['max_tokens'],
        temperature=config['temperature'],
        messages=[
            {"role": "system", "content": config['system_prompt']},
            {"role": "user", "content": prompt}
        ]
    )
    return response.content[0].text

def summarize_ollama(conversation, model, client, config):
    prompt = config['system_prompt'] + "\n\n" + config['user_prompt_template'].format(conversation=conversation)
    response = client.post(
        "http://localhost:11434/api/generate",
        json={"model": model, "prompt": prompt, "stream": False}
    )
    return response.json()["response"]

def summarize_gemini(conversation, model, client, config):
    full_prompt = f"{config['system_prompt']}\n\n{config['user_prompt_template'].format(conversation=conversation)}"
    response = client.generate_content(
        full_prompt,
        generation_config=genai.types.GenerationConfig(
            max_output_tokens=config['max_tokens'],
            temperature=config['temperature'],
        )
    )
    if not response.candidates:
        raise Exception("No response candidates returned from Gemini")
    candidate = response.candidates[0]
    if candidate.finish_reason == 2:
        raise Exception("Response blocked by Gemini safety filters")
    elif candidate.finish_reason == 3:
        raise Exception("Response blocked due to recitation concerns")
    elif candidate.finish_reason == 4:
        raise Exception("Response blocked for other reasons")
    if not candidate.content or not candidate.content.parts:
        raise Exception("No content parts in response")
    return candidate.content.parts[0].text

def create_llm_client(provider, api_key=None, model=None):
    provider = provider.lower()
    if provider == "openai":
        if not api_key:
            raise ValueError("OpenAI requires an api_key.")
        return OpenAI(api_key=api_key)
    elif provider == "claude":
        if not api_key:
            raise ValueError("Anthropic Claude requires an api_key.")
        return anthropic.Anthropic(api_key=api_key)
    elif provider == "ollama":
        return requests.Session()
    elif provider == "gemini":
        if not api_key:
            raise ValueError("Gemini requires an api_key.")
        if not model:
            raise ValueError("Gemini requires a model name.")
        genai.configure(api_key=api_key)
        return genai.GenerativeModel(model)
    else:
        raise ValueError(f"Unsupported provider: {provider}")

# --- Initialize enabled LLM clients ---
enabled_providers = get_enabled_providers()
print(f"Enabled LLM providers: {enabled_providers}")

# Initialize clients for enabled providers
llm_clients = {}

if 'gemini' in enabled_providers:
    gemini_api_key = os.getenv("GEMINI_API_KEY")
    gemini_model = get_model_for_provider("gemini")
    if gemini_api_key and gemini_model:
        try:
            llm_clients['gemini'] = {
                'client': create_llm_client("gemini", api_key=gemini_api_key, model=gemini_model),
                'model': gemini_model
            }
            print(f"Initialized Gemini client with model: {gemini_model}")
        except Exception as e:
            print(f"Error initializing Gemini client: {e}")

if 'openai' in enabled_providers:
    openai_api_key = os.getenv("OPENAI_API_KEY")
    openai_model = get_model_for_provider("openai")
    if openai_api_key and openai_model:
        try:
            llm_clients['openai'] = {
                'client': create_llm_client("openai", api_key=openai_api_key, model=openai_model),
                'model': openai_model
            }
            print(f"Initialized OpenAI client with model: {openai_model}")
        except Exception as e:
            print(f"Error initializing OpenAI client: {e}")

if 'claude' in enabled_providers:
    claude_api_key = os.getenv("CLAUDE_API_KEY")
    claude_model = get_model_for_provider("claude")
    if claude_api_key and claude_model:
        try:
            llm_clients['claude'] = {
                'client': create_llm_client("claude", api_key=claude_api_key, model=claude_model),
                'model': claude_model
            }
            print(f"Initialized Claude client with model: {claude_model}")
        except Exception as e:
            print(f"Error initializing Claude client: {e}")

if 'ollama' in enabled_providers:
    ollama_model = get_model_for_provider("ollama")
    if ollama_model:
        try:
            llm_clients['ollama'] = {
                'client': create_llm_client("ollama"),
                'model': ollama_model
            }
            print(f"Initialized Ollama client with model: {ollama_model}")
        except Exception as e:
            print(f"Error initializing Ollama client: {e}")



DISABLE_LLM = os.getenv('DISABLE_LLM', 'true').lower() in ('1', 'true', 'yes')

@router.get("/available-models")
async def get_available_models_endpoint():
    """
    Get list of available LLM models based on enabled providers.
    """
    try:
        available_models = get_available_models_for_enabled_providers()
        enabled_providers = get_enabled_providers()
        
        return {
            "available_models": available_models,
            "enabled_providers": enabled_providers,
            "disable_llm": DISABLE_LLM
        }
    except Exception as e:
        print(f"Error in /available-models: {e}")
        raise HTTPException(status_code=500, detail=f"Error getting available models: {str(e)}")

@router.post("/llm-summary")
async def llm_summary(data: LLMSummaryRequest):
    """
    Generate a summary using available LLM providers.
    """
    if DISABLE_LLM:
        # Return a random summary for testing
        random_summaries = [
            "The team discussed lighting and animation improvements.",
            "Minor tweaks needed for character animation; background approved.",
            "Action items: soften shadows, adjust highlight gain, improve hand motion.",
            "Most notes addressed; only a few minor issues remain.",
            "Ready for final review after next round of changes.",
            "Feedback: color grade is close, but highlights too hot.",
            "Artist to be notified about animation and lighting feedback.",
            "Overall progress is good; next steps communicated to the team."
        ]
        return {"summary": random.choice(random_summaries)}
    
    if not llm_clients:
        raise HTTPException(status_code=500, detail="No LLM clients initialized.")
    
    # Use the first available client (you could add logic to choose a specific one)
    provider = list(llm_clients.keys())[0]
    client_info = llm_clients[provider]
    client = client_info['client']
    model = client_info['model']
    
    try:
        config = get_model_config(provider, model)
        
        if provider == 'openai':
            summary = summarize_openai(data.text, model, client, config)
        elif provider == 'claude':
            summary = summarize_claude(data.text, model, client, config)
        elif provider == 'ollama':
            summary = summarize_ollama(data.text, model, client, config)
        elif provider == 'gemini':
            summary = summarize_gemini(data.text, model, client, config)
        else:
            raise HTTPException(status_code=500, detail=f"Unsupported provider: {provider}")
        
        return {"summary": summary, "provider": provider, "model": model}
    except Exception as e:
        print(f"Error in /llm-summary with {provider}: {e}")
        raise HTTPException(status_code=500, detail=f"LLM summary error: {str(e)}")

if __name__ == "__main__":
    import sys
    import argparse
    load_dotenv()
    parser = argparse.ArgumentParser(description="Test LLM summary functions.")
    parser.add_argument('--provider', choices=['openai', 'claude', 'gemini', 'ollama'], default='gemini', help='LLM provider to test')
    parser.add_argument('--text', type=str, default='Artist submitted new lighting pass for shot 101. Lead: Looks good, but highlights are too strong. Artist: Will reduce highlight gain and resubmit.', help='Conversation text to summarize')
    args = parser.parse_args()

    provider = args.provider
    text = args.text
    model = get_model_for_provider(provider)
    api_key = os.getenv(f'{provider.upper()}_API_KEY')
    print(f"Testing {provider} summary with model {model}...")
    try:
        client = create_llm_client(provider, api_key=api_key, model=model)
        config = get_model_config(provider, model, LLM_CONFIG)
        print(f"Using config: temperature={config['temperature']}, max_tokens={config['max_tokens']}")
        if provider == 'openai':
            summary = summarize_openai(text, model, client, config)
        elif provider == 'claude':
            summary = summarize_claude(text, model, client, config)
        elif provider == 'ollama':
            summary = summarize_ollama(text, model, client, config)
        elif provider == 'gemini':
            summary = summarize_gemini(text, model, client, config)
        else:
            print(f"Unknown provider: {provider}")
            sys.exit(1)
        print(f"Summary:\n{summary}")
    except Exception as e:
        print(f"Error: {e}")