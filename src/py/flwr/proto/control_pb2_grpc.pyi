"""
@generated by mypy-protobuf.  Do not edit manually!
isort:skip_file
"""
import abc
import flwr.proto.driver_pb2
import grpc

class ControlStub:
    def __init__(self, channel: grpc.Channel) -> None: ...
    CreateRun: grpc.UnaryUnaryMultiCallable[
        flwr.proto.driver_pb2.CreateRunRequest,
        flwr.proto.driver_pb2.CreateRunResponse]
    """Request to create a new run"""


class ControlServicer(metaclass=abc.ABCMeta):
    @abc.abstractmethod
    def CreateRun(self,
        request: flwr.proto.driver_pb2.CreateRunRequest,
        context: grpc.ServicerContext,
    ) -> flwr.proto.driver_pb2.CreateRunResponse:
        """Request to create a new run"""
        pass


def add_ControlServicer_to_server(servicer: ControlServicer, server: grpc.Server) -> None: ...
