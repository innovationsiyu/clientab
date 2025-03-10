from ast import literal_eval
import os
import requests
import time
import importlib
import random
import pandas as pd
import json
import ast
from charset_normalizer import detect
import codecs
from scraper import scrape_web_contents, parse_web_contents
from ab_time import now_in_filename, iso_date
from ab_utils import manage_thread, upload_to_container
from export_to_word import export_search_results_to_word, append_company_info_and_disclaimer
from ab_utils import retrieve

OPENROUTER_API_KEY = retrieve("OpenRouter")
EXCELLENCE_API_KEY = retrieve("ExcellenceKey")
EXCELLENCE_ENDPOINT = retrieve("ExcellenceEndpoint")


def execute(tool_calls):
    try:
        results = {
            f"{name}({arguments})": globals().get(name)(**literal_eval(arguments))
            for tool_call in tool_calls
            if (function := tool_call.get("function"))
            if (name := function.get("name")) and (arguments := function.get("arguments"))
            if name in globals()
        }
        return results
    except Exception as e:
        print(f"Failed to execute tool calls: {e}")
        return None


def request_llm(url, headers, data, delay=1):
    for attempt in range(3):
        try:
            print(f"Sending request to {url}")
            response = requests.post(url, headers=headers, json=data, timeout=180).json()
            print(response)
            if (message := response.get("choices", [{}])[0].get("message", {})):
                if (tool_calls := message.get("tool_calls")):
                    if (results := execute(tool_calls)):
                        return f"The following dictionary contains the results:\n{results}"
                elif (content := message.get("content")):
                    return content
            raise Exception("Invalid response or execution failed")
        except Exception as e:
            print(f"Attempt {attempt + 1} failed: {e}")
            if attempt < 2:
                time.sleep(delay)
                delay *= 2
    print("Failed to get a valid response after maximum retries")
    return None


class LLM:
    def __init__(self, url, api_key):
        self.url = url
        self.api_key = api_key

    def __call__(self, messages, model, temperature, top_p, response_format=None, tools=None):
        headers = {
            "Authorization": f"Bearer {self.api_key}"
        }
        data = {
            "messages": messages,
            "model": model,
            "temperature": temperature,
            "top_p": top_p,
            **({"response_format": response_format} if response_format else {}),
            **({"tools": tools} if tools else {})
        }
        return request_llm(self.url, headers, data)


class Azure:
    def __init__(self, endpoint, api_key):
        self.endpoint = endpoint
        self.api_key = api_key

    def __call__(self, messages, model, temperature, top_p, response_format=None, tools=None):
        url = f"{self.endpoint}openai/deployments/{model}/chat/completions?api-version=2024-10-21"
        headers = {
            "api-key": self.api_key
        }
        data = {
            "messages": messages,
            "temperature": temperature,
            "top_p": top_p,
            **({"response_format": response_format} if response_format else {}),
            **({"tools": tools} if tools else {})
        }
        return request_llm(url, headers, data)


openrouter = LLM("https://openrouter.ai/api/v1/chat/completions", OPENROUTER_API_KEY)
excellence = Azure(EXCELLENCE_ENDPOINT, EXCELLENCE_API_KEY)


def get_prompt(prompt, **arguments):
    if arguments:
        return getattr(importlib.import_module(f"ab_prompts.{prompt}"), prompt).format(**arguments)
    else:
        return getattr(importlib.import_module(f"ab_prompts.{prompt}"), prompt)


def get_response_format(response_format):
    if response_format:
        return getattr(importlib.import_module(f"ab_response_formats.{response_format}"), response_format)
    return None


def get_tools(tools):
    if tools:
        return [getattr(importlib.import_module("ab_tools"), tool) for tool in tools]
    return None


class Chat:
    def __call__(self, llms, messages, response_format=None, tools=None):
        for llm in llms:
            try:
                results = globals()[llm_dict[llm]["name"]](messages, **llm_dict[llm]["arguments"], response_format=response_format, tools=tools)
                if results:
                    return results
            except Exception:
                continue
        return None

chat = Chat()

def text_chat(ai, user_message):
    llms = ai_dict[ai]["llms"]
    system_message = get_prompt(ai_dict[ai]["system_message"])
    response_format = get_response_format(ai_dict[ai]["response_format"])
    tools = get_tools(ai_dict[ai]["tools"])
    messages = [{"role": "system", "content": system_message}, {"role": "user", "content": user_message}]
    return chat(llms, messages, response_format, tools)


ai_dict = {
    "GPT for text chat": {
        "category": "function_calling",
        "llms": ["gpt4o_excellence", "gpt4o_openrouter"],
        "system_message": "online_articles_to_word",
        "response_format": None,
        "tools": ["online_articles_from_url_to_word_func", "online_articles_from_raw_to_word_func"],
        "backend_ais": None,
        "max_length": 128000,
        "intro": "OpenAI: GPT-4o"
    },
    "GPT for extracting info from online article": {
        "category": "internal",
        "llms": ["gpt4o_excellence", "gpt4o_openrouter"],
        "system_message": "extract_info_from_online_article",
        "response_format": "extract_info_from_online_article_json",
        "tools": None,
        "backend_ais": None,
        "max_length": None,
        "intro": "internal"
    }
}

llm_dict = {
    "gpt4o_openrouter": {
        "name": "openrouter",
        "arguments": {
            "model": "openai/gpt-4o-2024-08-06",
            "temperature": 0.5,
            "top_p": 0.9
        }
    },
    "gpt4o_excellence": {
        "name": "excellence",
        "arguments": {
            "model": "excellence",
            "temperature": 0.5,
            "top_p": 0.9
        }
    }
}

online_articles_from_url_to_word_func = {
    "type": "function",
    "function": {
        "name": "online_articles_from_url_to_word",
        "description": "Scrape the webpages for the online articles, write them into a document and return a URL for downloading the document or a CSV file.",
        "parameters": {
            "type": "object",
            "properties": {
                "search_results": {
                    "type": "object",
                    "description": "A dictionary in which each key is a category name and the corresponding value is the list of URLs under that category.",
                },
            },
            "required": ["search_results"],
            "additionalProperties": False,
        },
    }
}

online_articles_from_raw_to_word_func = {
    "type": "function",
    "function": {
        "name": "online_articles_from_raw_to_word",
        "description": "Read the Excel or CSV file for the online articles, write them into a document and return a URL for downloading it.",
        "parameters": {
            "type": "object",
            "properties": {
                "file_path": {
                    "type": "string",
                    "description": "The path of the Excel or CSV file containing the content of each online article.",
                },
            },
            "required": ["file_path"],
            "additionalProperties": False,
        },
    }
}


def search_results_to_csv(search_results):
    csv_path = f"temp-data/{now_in_filename()}.csv"
    pd.DataFrame(columns=["web_url", "web_raw_content", "heading_1", "heading_2", "source", "published_date", "web_content", "body_content"]).to_csv(csv_path, index=False, encoding="utf-8")
    df = pd.read_csv(csv_path, encoding="utf-8")
    df = pd.concat([df, pd.DataFrame([{"heading_1": heading_1, "web_url": web_url}
        for heading_1, web_urls in search_results.items()
        for web_url in web_urls]).reindex(columns=df.columns)])
    df.to_csv(csv_path, index=False, encoding="utf-8")
    return csv_path


def web_contents_from_url_to_csv(csv_path, urls_per_chunk=6, interval_seconds=5):
    df = pd.read_csv(csv_path, encoding="utf-8")
    valid_mask = df["web_url"].notna()
    web_urls = df[valid_mask]["web_url"].tolist()
    web_url_chunks = [web_urls[i:i + urls_per_chunk] for i in range(0, len(web_urls), urls_per_chunk)]
    web_contents = {}
    for i, web_url_chunk in enumerate(web_url_chunks):
        web_contents.update(scrape_web_contents(web_url_chunk))
        if i < len(web_url_chunks) - 1:
            time.sleep(interval_seconds)
    df.loc[valid_mask, "web_content"] = df.loc[valid_mask, "web_url"].map(web_contents)
    df.to_csv(csv_path, index=False, encoding="utf-8")
    return len(web_urls)


def ensure_csv_utf8(table_path):
    try:
        if table_path.endswith(".csv"):
            with open(table_path, "rb") as f:
                encoding = codecs.lookup(detect(f.read(min(32768, os.path.getsize(table_path))))["encoding"]).name
            df = pd.read_csv(table_path, encoding=encoding)
        elif table_path.endswith((".xlsx", ".xls")):
            df = pd.read_excel(table_path, engine="openpyxl")
        else:
            return None
        first_valid_column = next((column for column in df.columns if pd.notna(column) or df[column].notna().any()), None)
        if first_valid_column:
            empty_mask = df[first_valid_column].isna()
            if empty_mask.any():
                df.loc[empty_mask, first_valid_column] = df.index[empty_mask]
            csv_path = os.path.splitext(table_path)[0] + ".csv"
            df.to_csv(csv_path, index=False, encoding="utf-8")
            return csv_path
    except Exception as e:
        print(f"Error in ensure_csv_utf8: {e}")
    return None


def web_contents_from_raw_to_csv(csv_path):
    df = pd.read_csv(csv_path, encoding="utf-8")
    valid_mask = df["web_raw_content"].notna()
    web_raw_contents = df[valid_mask]["web_raw_content"].tolist()
    web_contents = parse_web_contents(web_raw_contents)
    df.loc[valid_mask, "web_content"] = df.loc[valid_mask, "web_raw_content"].map(web_contents)
    df.to_csv(csv_path, index=False, encoding="utf-8")


def extend_body_content_bounds(web_content, body_content_bounds):
    start_bound, end_bound = body_content_bounds
    while start_bound - 1 in web_content and web_content[start_bound - 1].startswith("temp-images"):
        start_bound -= 1
    while end_bound + 1 in web_content and web_content[end_bound + 1].startswith("temp-images"):
        end_bound += 1
    return start_bound, end_bound


def extract_info_from_online_article(web_url, web_content, delay=1):
    ai = "GPT for extracting info from online article"
    user_message = f"<web_content>{(dict(list(web_content.items())[:80] + list(web_content.items())[-80:]) if len(web_content) > 160 else web_content)}</web_content>"
    for attempt in range(3):
        try:
            results = text_chat(ai, user_message)
            results = json.loads(results)
            title = results.get("title")
            source = results.get("source")
            published_date = iso_date(results.get("published_date"))
            body_content_bounds = results.get("body_content_bounds")
            if title and source and published_date and len(body_content_bounds) == 2:
                start_bound, end_bound = extend_body_content_bounds(web_content, body_content_bounds)
                body_content = {key: web_content[key] for key in range(start_bound, end_bound + 1) if key in web_content}
                return title, source, published_date, body_content
        except Exception as e:
            print(f"Attempt {attempt + 1} failed: {e}")
            if attempt < 2:
                time.sleep(delay)
                delay *= 2
    print("Failed to extract info after maximum retries")
    return None, None, None, None


def extract_info_from_online_articles(web_urls, web_contents):
    requests = [(extract_info_from_online_article, web_url, web_content) for web_url, web_content in zip(web_urls, web_contents)]
    return {arguments[0]: result for result, name, arguments in manage_thread(requests)}


def info_from_web_contents_to_csv(csv_path):
    df = pd.read_csv(csv_path, encoding="utf-8")
    valid_mask = df["web_content"].notna()
    web_urls = df[valid_mask]["web_url"].tolist()
    web_contents = [ast.literal_eval(web_content) for web_content in df[valid_mask]["web_content"].tolist()]
    info = extract_info_from_online_articles(web_urls, web_contents)
    df.loc[valid_mask, "heading_2"] = df.loc[valid_mask, "web_url"].map({web_url: values[0] for web_url, values in info.items()})
    df.loc[valid_mask, "source"] = df.loc[valid_mask, "web_url"].map({web_url: values[1] for web_url, values in info.items()})
    df.loc[valid_mask, "published_date"] = df.loc[valid_mask, "web_url"].map({web_url: values[2] for web_url, values in info.items()})
    df.loc[valid_mask, "body_content"] = df.loc[valid_mask, "web_url"].map({web_url: str(values[3]) if values[3] else None for web_url, values in info.items()})
    df.to_csv(csv_path, index=False, encoding="utf-8")
    return df.loc[valid_mask, ["heading_2", "source", "published_date", "body_content"]].notna().all(axis=1).sum()


def info_from_web_raw_contents_to_csv(csv_path):
    df = pd.read_csv(csv_path, encoding="utf-8")
    valid_mask = df["web_raw_content"].notna()
    web_urls = df[valid_mask]["web_url"].tolist()
    web_contents = [ast.literal_eval(web_content) for web_content in df[valid_mask]["web_content"].tolist()]
    info = extract_info_from_online_articles(web_urls, web_contents)
    df.loc[valid_mask, "heading_2"] = df.loc[valid_mask, "web_url"].map({web_url: values[0] for web_url, values in info.items()})
    df.loc[valid_mask, "source"] = df.loc[valid_mask, "web_url"].map({web_url: values[1] for web_url, values in info.items()})
    df.loc[valid_mask, "published_date"] = df.loc[valid_mask, "web_url"].map({web_url: values[2] for web_url, values in info.items()})
    df.loc[valid_mask, "body_content"] = df.loc[valid_mask, "web_url"].map({web_url: str(values[3]) if values[3] else None for web_url, values in info.items()})
    df.to_csv(csv_path, index=False, encoding="utf-8")


def online_articles_from_url_to_word(search_results):
    csv_path = search_results_to_csv(search_results)
    web_url_count = web_contents_from_url_to_csv(csv_path)
    article_info_count = info_from_web_contents_to_csv(csv_path)
    if web_url_count == article_info_count:
        doc_path = export_search_results_to_word(csv_path)
        append_company_info_and_disclaimer(doc_path)
        return upload_to_container(doc_path)
    else:
        return upload_to_container(csv_path)


def online_articles_from_raw_to_word(file_path):
    csv_path = ensure_csv_utf8(file_path)
    if csv_path:
        web_contents_from_raw_to_csv(csv_path)
        info_from_web_raw_contents_to_csv(csv_path)
        doc_path = export_search_results_to_word(csv_path)
        append_company_info_and_disclaimer(doc_path)
        return upload_to_container(doc_path)
    else:
        return None


if __name__ == "__main__":
    csv_path = ""

   # online_articles_from_url_to_word(search_results)
    online_articles_from_raw_to_word(csv_path)
