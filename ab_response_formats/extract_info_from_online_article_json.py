extract_info_from_online_article_json = {
    "type": "json_schema",
    "json_schema": {
        "name": "extract_info_from_online_article",
        "schema": {
            "type": "object",
            "properties": {
                "title": {
                    "type": "string",
                    "description": "The title of the article, excluding additional text and any punctuation."
                },
                "source": {
                    "type": "string",
                    "description": "The source of the article, using the official full name of the publishing institution or media outlet."
                },
                "published_date": {
                    "type": "string",
                    "description": "The published date of the article in ISO format."
                },
                "body_content_bounds": {
                    "type": "array",
                    "description": "A pair of line numbers, where the first number represents the start line and the second number represents the end line of the body content of the article.",
                    "items": {
                        "type": "integer",
                        "description": "A key (line number) in the dictionary of the webpage's content."
                    }
                }
            },
            "required": ["title", "source", "published_date", "body_content_bounds"],
            "additionalProperties": False
        },
        "strict": True
    }
}
