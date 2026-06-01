from app.config import get_settings


def main() -> None:
    settings = get_settings()
    target = settings.embedding_model_path
    if target.is_dir() and any(target.iterdir()):
        print(f"Embedding model already present at {target}")
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        from sentence_transformers import SentenceTransformer
    except ImportError as exc:
        raise SystemExit("Install sentence-transformers or project 'models' extra first") from exc
    model = SentenceTransformer(settings.embedding_model_name)
    model.save(str(target))
    print(f"Saved {settings.embedding_model_name} to {target}")


if __name__ == "__main__":
    main()
