from abc import ABC, abstractmethod

class IEpsilon(ABC):
    
    @abstractmethod
    def file_list(self, *args, **kwargs):
        pass

    @abstractmethod
    def file_detail(self, *args, **kwargs):
        pass
