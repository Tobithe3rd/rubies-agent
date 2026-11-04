import { cn } from "@/lib/utils";
import { copy } from "@/core/config";
import { OUTLINED_BUTTON, Section } from "@/features/panel/panel-ui";

export function TasksSection({
  loading,
  chatId,
  isSheet,
  onSend,
  onClose,
}: {
  loading: boolean;
  chatId: string | null;
  isSheet: boolean;
  onSend: (message: string) => void;
  onClose: () => void;
}) {
  return (
    <Section title={copy.panel.tasksTitle}>
      <div className="flex flex-col gap-2">
        {copy.tasks.map((task) => (
          <button
            key={task.label}
            type="button"
            disabled={loading || !chatId}
            onClick={() => {
              onSend(task.message);
              if (isSheet) onClose();
            }}
            className={cn(OUTLINED_BUTTON, "w-full justify-start text-left")}
          >
            {task.label}
          </button>
        ))}
      </div>
    </Section>
  );
}
