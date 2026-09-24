from rest_framework import status
from rest_framework.response import Response

from .models import EvalRun
from .runner import run_eval
from ..tasks import run_eval as run_eval_task
from ..utils.Permissions import IsAdminPermission
from ..utils.Views import SmartAPIView


class EvalRunNow(SmartAPIView):
    permission_classes = [IsAdminPermission]

    def post(self, request):
        body = request.data if isinstance(request.data, dict) else {}
        provider = body.get("provider") or None
        if body.get("async"):
            run_eval_task.delay(provider)
            return Response({"queued": True}, status=status.HTTP_202_ACCEPTED)
        return Response(run_eval(provider), status=status.HTTP_200_OK)


class EvalRunList(SmartAPIView):
    permission_classes = [IsAdminPermission]

    def get(self, request):
        rows = EvalRun.objects.order_by("-started_at")[:50]
        return Response(
            {
                "runs": [
                    {
                        "id": row.id,
                        "started_at": row.started_at,
                        "finished_at": row.finished_at,
                        "prompt_versions": row.prompt_versions,
                        "provider": row.provider,
                        "passed": row.passed,
                        "failed": row.failed,
                        "results": row.results,
                    }
                    for row in rows
                ]
            }
        )
