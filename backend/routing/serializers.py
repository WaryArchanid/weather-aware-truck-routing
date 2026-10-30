from rest_framework import serializers

class TripAnalyzerRequestSerializer(serializers.Serializer):
    origin = serializers.CharField(max_length=200)
    destination = serializers.CharField(max_length=200)
    departure_datetime = serializers.DateTimeField()
    load_weight = serializers.IntegerField(min_value=1)
    checkpoint_interval_miles = serializers.ChoiceField(
        choices=[10, 25, 50],
        default=25
    )

    def validate(self, attrs):
        origin = attrs["origin"].strip().casefold()
        destination = attrs["destination"].strip().casefold()

        if origin == destination:
            raise serializers.ValidationError({
                "destination": (
                    "Destination must be different from origin."
                )
            })
        return attrs