import sys
import logging
import pandas as pd

from langchain_openai import ChatOpenAI
from sklearn.metrics import cohen_kappa_score


PROMPT = """
You are an expert software engineering researcher trying to perform open-coding on repository READMEs.
You are given a repository name and a README file from a GitHub repository with a track record of faking GitHub stars, and 
you are tasked with categorizing the README into one of the following categories:

* `suspicious`: The repository is one of the following cases: 
    (a) it is an obvious clickbait (e.g., claiming game cheats, pirated software, cryptocurrency bots) to trick download of suspicious files, 
    (b) it is spreading spam advertising content, possibly used for search engine optimizations, or 
    (c) it does not contain anything meaningful and thus looks highly suspicious. 
* `ai`: The repository is generally related to AI or large language models (LLMs).
    Many of repositories in this category are academic paper repositories or repositories for LLM-related startup products.
    If the repository appears like a demo, toy, tutorial, or a list of AI-related references (e.g., awesome LLM tools), 
    put it into the `tutorial/demo` category.
* `blockchain`: The repository is generally related to blockchain, containing terms related to cryptocurrencies, decentralized finance, 
   or Web 3.0 technologies. Plus, it appears to be a piece of legitimate software. 
   Otherwise, if it appears like a tutorial or list of references, put it into the `tutorial/demo` category; 
   if it does not appear to contain any meaningful documentation or source code, put it into the `suspicious` category.
* `web`: The repository is generally a web framework or library serving the purpose of web development (e.g., platforms for blogging or e-commerce, 
    UI design frameworks, microservice frameworks). Again, if it appears like a demo, template, starter kit, or a list of references,
    (e.g., a template for vue.js development), put it into the `tutorial/demo` category.
* `tutorial/demo`: The repository either 
   (a) generally provides reference/educational information for someone else;
   (b) generally looks like a toy project or a demo project; or
   (c) generally provides a starter template for a certain framework.
* `tool/application`: The repository is a (seemingly legitimate) piece of tool or application (e.g., command-line tools or Android apps),
     that are not blockchain-related, AI/LLM-related, or database-related. Do not put a repository here if it is a library or a framework.
* `basic-utility`: The repository is a software library providing basic utility functions (e.g., caching, exception handling). 
    Do not put a repository here if it is providing functionality specific to web development (label as `web` instead).
* `database`: The repository is generally related to database. It may be a database solution in itself (e.g., a certain type of database run by a startup), 
    or supporting libraries/tools for databases.
* `other`: All other repositories that cannot be fit into any of the above categories.

I would like you to only provide a final category string exactly as stated above, without encapsulating ``s.
Do not provide any additional comments or explanations.

The repository is {repo} and the REAMDE file is as follows:

```
{readme}
```
"""

def get_ai_labels():
    df = pd.read_csv("data/repo_labels.csv")
    readmes = pd.read_csv("data/readmes/summary.csv")
    repo_to_readmes = dict(zip(readmes.repo, readmes.readme))
    ai_labels = []
    for repo, human_label in zip(df.repo, df.domain):
        if repo not in repo_to_readmes:
            logging.info(f"README of {repo} not found.")
            ai_labels.append(None)
            continue

        with open(repo_to_readmes[repo], "r") as f:
            readme = f.read()

        llm = ChatOpenAI(model="o3-mini")
        output = llm.invoke(PROMPT.format(repo=repo,readme=readme))
        print(f"{repo}: human={human_label}, ai={output.content.strip()}")
        ai_labels.append(output.content.strip())
    df["ai_label"] = ai_labels
    df.to_csv("data/repo_labels.csv", index=False)


def main():    
    logging.basicConfig(
        format="%(asctime)s (PID %(process)d) [%(levelname)s] %(filename)s:%(lineno)d %(message)s",
        level=logging.INFO,
        handlers=[logging.StreamHandler(sys.stdout)],
    )

    df = pd.read_csv("data/repo_labels.csv")

    # get_ai_labels()  

    df_compare = df[df.domain.notna() & df.ai_label.notna() & ~df.domain.isin(["deleted", "bot"])]
    print(cohen_kappa_score(df_compare.domain, df_compare.ai_label))
    

if __name__ == "__main__":
    main()