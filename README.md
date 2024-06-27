# Fake-Star-Detector

This is a project to detect fake stars in popular github repos

## Dev Setup

1. Setup Python env. For example (using Anaconda):

```shell
conda create -n fake-star python=3.12
conda activate fake-star
pip install -r requirements.txt
```

2. Configuring Secrets in `secrets.yaml`

```yaml
mongo_url: "your_mongo_url"
github_tokens:
  - token: "your_github_token"
    name: "your_github_username"
  - token: "your_github_token"
    name: "your_github_username"
```