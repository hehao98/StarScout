import matplotlib
import matplotlib.pyplot as plt


EVENT_ORDER = ["Star", "Push", "Fork", "Create", "Issue", "PR", "Comment", "Other"]


def init_matplotlib():
    matplotlib.style.use("seaborn-v0_8-colorblind")

    for path in matplotlib.font_manager.findSystemFonts():
        f = matplotlib.font_manager.get_font(path)
        if f.family_name == "Times New Roman":
            matplotlib.font_manager.fontManager.addfont(path)
            prop = matplotlib.font_manager.FontProperties(fname=path)
            plt.rcParams["font.family"] = "serif"
            plt.rcParams["font.sans-serif"] = prop.get_name()

    setattr(plt.Axes, "remove_spines", remove_spines)


def shorten_gharchive_event(event: str) -> str:
    event = event.replace("Event", "")
    if event == "PullRequest":
        return "PR"
    if event == "Watch":
        return "Star"
    if event == "Issues":
        return "Issue"
    if "Comment" in event or "Review" in event:
        return "Comment"
    if event not in EVENT_ORDER:
        return "Other"
    return event


def remove_spines(ax: plt.Axes):
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
