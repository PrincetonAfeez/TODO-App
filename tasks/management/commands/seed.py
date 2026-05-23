from django.contrib.sessions.models import Session
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from tasks import services
from tasks.models import RecurrenceFrequency, TaskList, TaskPriority


class Command(BaseCommand):
    help = "Seed a demo session with lists, tasks, subtasks, and recurrence."

    def add_arguments(self, parser):
        parser.add_argument(
            "--force",
            action="store_true",
            help="Delete existing data for the target session before re-seeding.",
        )
        parser.add_argument(
            "--session-key",
            default=None,
            help="Attach demo data to this session key (default: seed-session).",
        )
        parser.add_argument(
            "--latest-session",
            action="store_true",
            help="Use the most recently touched Django session (visit the app first).",
        )

    def handle(self, *args, **options):
        if options["latest_session"]:
            if options["session_key"] is not None:
                raise CommandError(
                    "Use either --session-key or --latest-session, not both."
                )
            latest = Session.objects.order_by("-expire_date").first()
            if latest is None:
                raise CommandError(
                    "No browser sessions found. Open the app once, then re-run with "
                    "--latest-session."
                )
            session_key = latest.session_key
        else:
            session_key = options["session_key"] or "seed-session"

        if options["force"]:
            TaskList.objects.filter(session_key=session_key).delete()
            self.stdout.write(
                self.style.WARNING(
                    f"Removed existing data for session {session_key!r}."
                )
            )

        inbox, _ = TaskList.objects.get_or_create(session_key=session_key, name="Inbox")
        work, _ = TaskList.objects.get_or_create(session_key=session_key, name="Work")

        if inbox.tasks.exists() or work.tasks.exists():
            self.stdout.write(
                self.style.WARNING(
                    f"Seed data already exists for session {session_key!r}. "
                    "Use --force to replace it."
                )
            )
            return

        grocery = services.create_task(
            task_list=inbox,
            title="Pick up groceries",
            notes="Milk, fruit, coffee",
            due_date=timezone.now() + timezone.timedelta(hours=6),
            priority=TaskPriority.MEDIUM,
        )
        services.create_task(task_list=inbox, parent=grocery, title="Check pantry")
        services.create_task(task_list=inbox, parent=grocery, title="Bring tote bags")

        services.create_task(
            task_list=inbox,
            title="Pay utility bill",
            due_date=timezone.now() - timezone.timedelta(days=2),
            priority=TaskPriority.HIGH,
        )

        archived = services.create_task(
            task_list=inbox,
            title="Old draft note",
            notes="Soft-deleted for demo",
            priority=TaskPriority.LOW,
        )
        services.soft_delete_task(archived)

        recurring = services.create_task(
            task_list=work,
            title="Send weekly update",
            due_date=timezone.now() + timezone.timedelta(days=1),
            priority=TaskPriority.HIGH,
        )
        services.set_recurrence(
            recurring,
            frequency=RecurrenceFrequency.WEEKLY,
            interval=1,
            weekday_mask=16,
        )

        monthly = services.create_task(
            task_list=work,
            title="Close books",
            due_date=timezone.now() + timezone.timedelta(days=5),
            priority=TaskPriority.MEDIUM,
        )
        services.set_recurrence(
            monthly,
            frequency=RecurrenceFrequency.MONTHLY,
            interval=1,
            day_of_month=31,
            end_date=timezone.localdate() + timezone.timedelta(days=90),
        )

        review = services.create_task(
            task_list=work,
            title="Review roadmap",
            due_date=timezone.now() + timezone.timedelta(days=3),
            priority=TaskPriority.HIGH,
        )
        services.toggle_task(review)

        standup = services.create_task(
            task_list=work,
            title="Prep standup notes",
            due_date=timezone.now() + timezone.timedelta(hours=4),
            priority=TaskPriority.MEDIUM,
        )
        services.toggle_task(standup)
        services.toggle_task(standup)

        self.stdout.write(
            self.style.SUCCESS(
                f"Seeded demo data for session {session_key!r} "
                f"({inbox.tasks.count() + work.tasks.count()} active tasks, "
                "overdue/deleted/recurring/completed examples, audit events)."
            )
        )
