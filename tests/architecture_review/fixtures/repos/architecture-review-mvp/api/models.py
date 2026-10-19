from sqlalchemy import Column, Integer, String


class Item:
    id = Column(Integer, primary_key=True)
    name = Column(String)


def get_items():
    return []