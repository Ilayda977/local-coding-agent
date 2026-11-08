"""Comments on tasks, with @mentions."""
import events
from common.errors import PermissionDeniedError
from common.validation import require_text
from comments.mentions import extract_mentions
from comments.models import Comment
from projects import permissions


class CommentService:
    def __init__(self, repository, tasks, projects, users, ids, clock, bus):
        self._comments = repository
        self._tasks = tasks
        self._projects = projects
        self._users = users
        self._ids = ids
        self._clock = clock
        self._bus = bus

    def _project_of(self, task_id):
        task = self._tasks.get(task_id)
        return task, self._projects.get(task.project_id)

    def _resolve_mentions(self, project, author_id, body):
        """Users that a comment may notify: existing project members, not the author."""
        mentioned = []
        for handle in extract_mentions(body):
            user = self._users.find_by_handle(handle)
            if user is None or user.id == author_id or user.id in mentioned:
                continue
            if not permissions.can_view(project, user.id):
                continue  # never notify people about projects they cannot see
            mentioned.append(user.id)
        return mentioned

    def add(self, task_id, author_id, body):
        task, project = self._project_of(task_id)
        self._users.require_active(author_id)
        permissions.require(permissions.can_comment(project, author_id),
                            f"user {author_id} cannot comment on {task_id}")
        body = require_text(body, "comment", max_length=2000)
        comment = Comment(id=self._ids.next(), task_id=task.id, author_id=author_id, body=body,
                          created_at=self._clock.now(),
                          mentioned_ids=self._resolve_mentions(project, author_id, body))
        self._comments.add(comment)
        self._bus.publish(events.COMMENT_ADDED, comment_id=comment.id, task_id=task.id,
                          author_id=author_id, mentioned_ids=list(comment.mentioned_ids))
        return comment

    def list_for_task(self, task_id, user_id):
        _task, project = self._project_of(task_id)
        permissions.require(permissions.can_view(project, user_id),
                            f"user {user_id} cannot view {task_id}")
        items = self._comments.list(lambda c: c.task_id == task_id)
        return sorted(items, key=lambda c: c.created_at)

    def edit(self, comment_id, user_id, body):
        comment = self._comments.get(comment_id)
        if comment.author_id != user_id:
            raise PermissionDeniedError("only the author can edit a comment")
        _task, project = self._project_of(comment.task_id)
        permissions.require(permissions.can_comment(project, user_id), "project is read-only")
        comment.body = require_text(body, "comment", max_length=2000)
        comment.edited_at = self._clock.now()
        return self._comments.update(comment)

    def delete(self, comment_id, user_id):
        comment = self._comments.get(comment_id)
        _task, project = self._project_of(comment.task_id)
        if comment.author_id != user_id and not permissions.can_manage(project, user_id):
            raise PermissionDeniedError("only the author or the owner can delete a comment")
        self._comments.remove(comment_id)
