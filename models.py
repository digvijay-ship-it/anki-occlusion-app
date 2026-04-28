from dataclasses import dataclass, field, asdict
from typing import List, Optional, Any, Dict
from datetime import datetime

@dataclass
class Box:
    rect: List[float] = field(default_factory=lambda: [0.0, 0.0, 100.0, 100.0])
    label: str = ""
    shape: str = "rect"
    angle: float = 0.0
    group_id: str = ""
    page_num: int = 0
    box_id: str = ""
    
    # SM2 fields
    sm2_interval: int = 0
    sm2_repetitions: int = 0
    sm2_ease: float = 2.5
    sm2_due: Optional[str] = None
    sm2_last_quality: int = 0
    sched_state: str = "new"
    sched_step: int = 0
    reviews: int = 0
    revealed: bool = False
    reviewed_at: Optional[str] = None
    last_quality: int = -1
    
    # Extra fields not strictly defined
    _extra: Dict[str, Any] = field(default_factory=dict, repr=False, compare=False)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Box":
        if not data:
            return cls()
        kwargs = {}
        extra = {}
        for key, value in data.items():
            if key in cls.__dataclass_fields__ and key != "_extra":
                kwargs[key] = value
            else:
                extra[key] = value
        obj = cls(**kwargs)
        obj._extra = extra
        return obj

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        extra = d.pop("_extra", {})
        d.update(extra)
        # Drop None values to keep JSON clean like before (optional, but good practice)
        return {k: v for k, v in d.items() if v is not None}

    def get(self, key: str, default: Any = None) -> Any:
        if hasattr(self, key):
            val = getattr(self, key)
            return default if val is None else val
        return self._extra.get(key, default)

    def __getitem__(self, key: str) -> Any:
        if hasattr(self, key):
            return getattr(self, key)
        return self._extra[key]

    def __setitem__(self, key: str, value: Any) -> None:
        if hasattr(self, key):
            setattr(self, key, value)
        else:
            self._extra[key] = value

    def __contains__(self, key: str) -> bool:
        return hasattr(self, key) or key in self._extra

    def pop(self, key: str, default: Any = None) -> Any:
        if hasattr(self, key):
            val = getattr(self, key)
            setattr(self, key, None)
            return val
        return self._extra.pop(key, default)

@dataclass
class Card:
    _id: str = ""
    title: str = "Untitled"
    tags: List[str] = field(default_factory=list)
    notes: str = ""
    boxes: List[Box] = field(default_factory=list)
    created: str = field(default_factory=lambda: datetime.now().isoformat())
    reviews: int = 0
    pdf_path: Optional[str] = None
    image_path: Optional[str] = None
    _auto_subdeck: Optional[str] = None
    last_reviewed_at: Optional[str] = None
    
    # SM2 fields (for cards without boxes)
    sm2_interval: int = 1
    sm2_repetitions: int = 0
    sm2_ease: float = 2.5
    sm2_due: Optional[str] = None
    sm2_last_quality: int = -1
    sched_state: str = "new"
    sched_step: int = 0

    _extra: Dict[str, Any] = field(default_factory=dict, repr=False, compare=False)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Card":
        if not data:
            return cls()
        kwargs = {}
        extra = {}
        for key, value in data.items():
            if key == "boxes":
                kwargs[key] = [Box.from_dict(b) if isinstance(b, dict) else b for b in value]
            elif key in cls.__dataclass_fields__ and key != "_extra":
                kwargs[key] = value
            else:
                extra[key] = value
        obj = cls(**kwargs)
        obj._extra = extra
        return obj

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        extra = d.pop("_extra", {})
        d.update(extra)
        
        # Manually serialize boxes correctly
        if "boxes" in d:
            d["boxes"] = [b.to_dict() if isinstance(b, Box) else b for b in self.boxes]
            
        return {k: v for k, v in d.items() if v is not None}

    # Helper for dictionary-like access to ease migration temporarily if needed
    def get(self, key: str, default: Any = None) -> Any:
        if hasattr(self, key):
            val = getattr(self, key)
            return default if val is None else val
        return self._extra.get(key, default)
    
    def __getitem__(self, key: str) -> Any:
        if hasattr(self, key):
            return getattr(self, key)
        return self._extra[key]
        
    def __setitem__(self, key: str, value: Any) -> None:
        if hasattr(self, key):
            setattr(self, key, value)
        else:
            self._extra[key] = value

    def pop(self, key: str, default: Any = None) -> Any:
        if hasattr(self, key):
            val = getattr(self, key)
            setattr(self, key, None)
            return val
        return self._extra.pop(key, default)

    def update(self, other: Dict[str, Any]) -> None:
        for k, v in other.items():
            self.__setitem__(k, v)

@dataclass
class Deck:
    _id: int = 0
    name: str = ""
    cards: List[Card] = field(default_factory=list)
    children: List["Deck"] = field(default_factory=list)
    expanded: bool = False
    
    _extra: Dict[str, Any] = field(default_factory=dict, repr=False, compare=False)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Deck":
        if not data:
            return cls()
        kwargs = {}
        extra = {}
        for key, value in data.items():
            if key == "cards":
                kwargs[key] = [Card.from_dict(c) if isinstance(c, dict) else c for c in value]
            elif key == "children":
                kwargs[key] = [Deck.from_dict(d) if isinstance(d, dict) else d for d in value]
            elif key in cls.__dataclass_fields__ and key != "_extra":
                kwargs[key] = value
            else:
                extra[key] = value
        obj = cls(**kwargs)
        obj._extra = extra
        return obj

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        extra = d.pop("_extra", {})
        d.update(extra)
        
        # Serialize nested
        if "cards" in d:
            d["cards"] = [c.to_dict() if isinstance(c, Card) else c for c in self.cards]
        if "children" in d:
            d["children"] = [child.to_dict() if isinstance(child, Deck) else child for child in self.children]
            
        return {k: v for k, v in d.items() if v is not None}

    def get(self, key: str, default: Any = None) -> Any:
        if hasattr(self, key):
            val = getattr(self, key)
            return default if val is None else val
        return self._extra.get(key, default)

    def __getitem__(self, key: str) -> Any:
        if hasattr(self, key):
            return getattr(self, key)
        return self._extra[key]

    def __setitem__(self, key: str, value: Any) -> None:
        if hasattr(self, key):
            setattr(self, key, value)
        else:
            self._extra[key] = value
